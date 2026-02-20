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
    """Базовый фильтр для режима FILTER_FIRST"""
    if not text: return False
    keywords = ['сдам', 'сдаю', 'сдается', 'сдаётся', 'сдаем', 'сдача']
    t_lower = text.lower()
    return any(word in t_lower for word in keywords)

async def process_with_ai(text, city_context):
    """ИИ-Парсер на базе твоего рабочего метода"""
    # Оставляем модель gemini-2.5-flash, как в твоем рабочем коде
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    prompt = f"""
    Ты — эксперт-модератор недвижимости в г. {city_context}.
    Проанализируй текст. Если это ПРЕДЛОЖЕНИЕ жилья (сдача) — вытяни данные.
    Если это ПОИСК (сниму, ищу) или мусор — поставь "is_ad": false.

    JSON СТРУКТУРА:
    {{
      "is_ad": boolean,
      "deal_type": "rent",
      "property_type": "apartment" | "room" | "studio" | "house" | "coliving",
      "price_value": number | null,
      "deposit_value": number | null,
      "rooms": number | null,
      "area_sqm": number | null,
      "address_raw": "string | null",
      "contact_phone": "только цифры 79...",
      "contact_tg": "username без @"
    }}
    
    Правила для rooms: 
    - Если это комната (room) или студия (studio) - всегда 1.
    - Если квартира (apartment) - реальное кол-во.
    
    Текст: {text}
    """
    
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"}
    ]

    try:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "safetySettings": safety_settings
        }
        resp = requests.post(url, json=payload, timeout=30)
        res_json = resp.json()
        raw_ai_text = res_json['candidates'][0]['content']['parts'][0]['text']
        # Чистим JSON
        clean_json = raw_ai_text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"⚠️ Ошибка ИИ для текста: {e}")
        return None

async def main():
    print(f"🚀 Запуск Завода. Цель: {TARGET_DATE.date()}")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    # 1. ПОЛУЧАЕМ ПАСПОРТА КАНАЛОВ
    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    
    for ch in res_ch.data:
        print(f"📡 Канал: {ch['username']} (Режим: {ch['processing_mode']})")
        
        async for msg in client.iter_messages(ch['username'], offset_date=TARGET_DATE + timedelta(days=1), limit=100):
            if msg.date.date() < TARGET_DATE.date():
                break 
            if msg.date.date() > TARGET_DATE.date():
                continue 
            
            if not msg.text: continue

            should_process = False
            if ch['processing_mode'] == 'AI_ONLY':
                should_process = True 
            else:
                if is_rent_keyword_found(msg.text):
                    should_process = True 
            
            status = "new" if should_process else "ignored"
            
            supabase.table("eraw_posts").upsert({
                "channel_id": ch['id'],
                "tg_post_id": msg.id,
                "text": msg.text,
                "status": status,
                "created_at": msg.date.isoformat()
            }, on_conflict="channel_id, tg_post_id").execute()

    # 2. ОБРАБОТКА ИИ (Твоя рабочая очередь)
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").execute()
    
    for post in res_new.data:
        channel_info = next((item for item in res_ch.data if item["id"] == post["channel_id"]), None)
        city = channel_info.get('target_city', 'Россия') if channel_info else 'Россия'
        
        print(f"🧐 ИИ анализирует пост {post['id']}...")
        ai_data = await process_with_ai(post['text'], city)
        
        if ai_data:
            # А) В eparsed_posts
            supabase.table("eparsed_posts").insert({
                "raw_post_id": post['id'],
                "is_ad": ai_data.get('is_ad', False),
                "json_data": ai_data
            }).execute()

            # Б) В eready_ads (если это объявление)
            if ai_data.get('is_ad') is True:
                # Генерируем ссылки
                ch_user = channel_info.get('username', 'channel').replace('@', '')
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
                    print(f"✅ Готово: {ai_data.get('property_type')} за {ai_data.get('price_value')}")
                except Exception as e:
                    print(f"⚠️ Ошибка в витрину: {e}")

            supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        else:
            supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()
            
        await asyncio.sleep(12) # Твоя рабочая пауза

    await client.disconnect()
    print("🏁 Работа завершена.")

if __name__ == "__main__":
    asyncio.run(main())
