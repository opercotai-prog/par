import os
import asyncio
import json
import requests
import re
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- НАСТРОЙКИ ---
API_ID = os.environ.get('TG_API_ID')
API_HASH = os.environ.get('TG_API_HASH')
SESSION_STRING = os.environ.get('TG_SESSION_STRING')
GEMINI_KEY = os.environ.get('GEMINI_KEY')
SUPABASE_URL = os.environ.get('SUPABASEE_URL') 
SUPABASE_KEY = os.environ.get('SUPABASEE_KEY')

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Целевая дата
TARGET_DATE = datetime(2026, 2, 17, tzinfo=timezone.utc)

def is_rent_keyword_found(text):
    if not text: return False
    keywords = ['сдам', 'сдаю', 'сдается', 'сдаётся', 'сдаем', 'сдача']
    return any(word in text.lower() for word in keywords)

async def process_with_ai(text, city_context):
    city_name = city_context if city_context else "Тюмень"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    prompt = f"""
    Верни JSON строго по схеме. Если данных нет - null.
    г. {city_name}. Только предложения СДАТЬ (is_ad: true).
    
    ПРАВИЛА ДЛЯ rooms:
    - Если сдается комната (room) или студия (studio) - всегда rooms: 1.
    - Если квартира (apartment) - реальное кол-во из текста.

    JSON:
    {{
      "is_ad": boolean,
      "deal_type": "rent",
      "property_type": "apartment" | "room" | "studio" | "house",
      "price_value": number,
      "deposit_value": number,
      "rooms": number,
      "area_sqm": number,
      "address_raw": "string",
      "contact_phone": "string",
      "contact_tg": "string"
    }}
    Текст: {text}
    """
    
    try:
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(url, json=payload, timeout=30)
        res_json = resp.json()
        
        if 'candidates' not in res_json:
            print(f"⚠️ Ошибка Gemini (Safety/Quota): {res_json}")
            return None

        raw_ai_text = res_json['candidates'][0]['content']['parts'][0]['text']
        # Находим JSON внутри ответа
        match = re.search(r'(\{.*\})', raw_ai_text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return None
    except Exception as e:
        print(f"❌ Ошибка парсинга: {e}")
        return None

async def main():
    print(f"🚀 Запуск Завода v3.7. Цель: {TARGET_DATE.date()}")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    # 1. СБОР ИСТОРИИ
    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    for ch in res_ch.data:
        print(f"📡 Сбор канала: {ch['username']}")
        
        async for msg in client.iter_messages(ch['username'], offset_date=TARGET_DATE + timedelta(days=1), limit=100):
            if msg.date.date() < TARGET_DATE.date(): break 
            if msg.date.date() > TARGET_DATE.date(): continue 
            if not msg.text: continue

            should_process = True if ch['processing_mode'] == 'AI_ONLY' else is_rent_keyword_found(msg.text)
            status = "new" if should_process else "ignored"
            
            supabase.table("eraw_posts").upsert({
                "channel_id": ch['id'],
                "tg_post_id": msg.id,
                "text": msg.text, # Используем чистый текст для экономии
                "status": status,
                "created_at": msg.date.isoformat()
            }, on_conflict="channel_id, tg_post_id").execute()

    # 2. ОБРАБОТКА ОЧЕРЕДИ
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").execute()
    print(f"📦 В очереди на ИИ: {len(res_new.data)} постов")
    
    for post in res_new.data:
        ch_info = next((i for i in res_ch.data if i["id"] == post["channel_id"]), None)
        city = ch_info.get('target_city') if ch_info else "Тюмень"
        
        print(f"🧐 ИИ анализирует {post['id']} ({city})...")
        ai_data = await process_with_ai(post['text'], city)
        
        if ai_data:
            # А) Сохраняем в eparsed_posts
            supabase.table("eparsed_posts").insert({
                "raw_post_id": post['id'],
                "is_ad": ai_data.get('is_ad', False),
                "json_data": ai_data
            }).execute()

            # Б) Сохраняем в eready_ads
            if ai_data.get('is_ad'):
                ch_user = ch_info.get('username', 'channel').replace('@', '')
                source_url = f"https://t.me/{ch_user}/{post['tg_post_id']}"
                main_photo_url = f"https://t.me/{ch_user}/{post['tg_post_id']}?embed=1"

                try:
                    supabase.table("eready_ads").upsert({
                        "raw_post_id": post['id'],
                        "channel_id": post['channel_id'],
                        "deal_type": "rent",
                        "property_type": ai_data.get('property_type'),
                        "price_value": ai_data.get('price_value'),
                        "deposit_value": ai_data.get('deposit_value'),
                        "rooms": ai_data.get('rooms'),
                        "area_sqm": ai_data.get('area_sqm'),
                        "address_raw": ai_data.get('address_raw'),
                        "contact_phone": ai_data.get('contact_phone'),
                        "contact_tg": ai_data.get('contact_tg'),
                        "source_url": source_url,
                        "main_photo_url": main_photo_url
                    }, on_conflict="raw_post_id").execute()
                    print(f"✅ Готово: {ai_data.get('price_value')} руб.")
                except Exception as e:
                    print(f"⚠️ Ошибка в витрину: {e}")

            supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        else:
            supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()
        
        await asyncio.sleep(15) # Идеальный темп для бесплатного ИИ

    await client.disconnect()
    print("🏁 Смена завершена.")

if __name__ == "__main__":
    asyncio.run(main())
