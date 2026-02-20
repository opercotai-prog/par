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
    keywords = ['сдам', 'сдаю', 'сдается', 'сдаётся', 'сдаем', 'сдача', 'пересдам']
    return any(word in text.lower() for word in keywords)

async def process_with_ai(text, city_context):
    # Исправляем проблему None
    city_name = city_context if city_context and city_context != "None" else "Тюмень"
    
    # ИСПОЛЬЗУЕМ МОДЕЛЬ 1.5-FLASH (высокие лимиты)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
    
    prompt = f"""
    Ты — эксперт-модератор недвижимости в г. {city_name}.
    Проанализируй текст. Если это ПРЕДЛОЖЕНИЕ жилья (сдача) — вытяни данные.
    Если это ПОИСК (сниму, ищу) или мусор — поставь "is_ad": false.

    ПРАВИЛА ДЛЯ ПОЛЯ rooms:
    1. Если property_type "room" (комната, подселение) или "studio" — всегда rooms: 1.
    2. Если "apartment" — реальное кол-во комнат из текста.

    ВЫДАЙ СТРОГИЙ JSON:
    {{
      "is_ad": boolean,
      "deal_type": "rent",
      "property_type": "apartment" | "room" | "studio" | "house",
      "price_value": number | null,
      "deposit_value": number | null,
      "rooms": number | null,
      "area_sqm": number | null,
      "address_raw": "string | null",
      "contact_phone": "только цифры 79...",
      "contact_tg": "username без @"
    }}
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
        resp = requests.post(url, json=payload, timeout=35)
        res_json = resp.json()
        
        # Обработка лимитов (Error 429)
        if 'error' in res_json:
            if res_json['error']['code'] == 429:
                return "LIMIT_EXCEEDED"
            print(f"⚠️ Ошибка API: {res_json['error']['message']}")
            return None

        if 'candidates' not in res_json:
            return None

        raw_ai_text = res_json['candidates'][0]['content']['parts'][0]['text']
        match = re.search(r'(\{.*\})', raw_ai_text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return None
    except Exception as e:
        print(f"❌ Ошибка парсинга: {e}")
        return None

async def main():
    print(f"🚀 Запуск Завода v3.8 (1.5-Flash). Цель: {TARGET_DATE.date()}")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    # 1. СБОР ИСТОРИИ
    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    for ch in res_ch.data:
        print(f"📡 Сбор: {ch['username']}")
        async for msg in client.iter_messages(ch['username'], offset_date=TARGET_DATE + timedelta(days=1), limit=100):
            if msg.date.date() < TARGET_DATE.date(): break 
            if msg.date.date() > TARGET_DATE.date(): continue 
            if not msg.text: continue

            should_process = True if ch['processing_mode'] == 'AI_ONLY' else is_rent_keyword_found(msg.text)
            status = "new" if should_process else "ignored"
            
            supabase.table("eraw_posts").upsert({
                "channel_id": ch['id'],
                "tg_post_id": msg.id,
                "text": msg.message, # Markdown для ссылок
                "status": status,
                "created_at": msg.date.isoformat()
            }, on_conflict="channel_id, tg_post_id").execute()

    # 2. ОБРАБОТКА ОЧЕРЕДИ
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").execute()
    print(f"📦 В очереди: {len(res_new.data)}")
    
    for post in res_new.data:
        ch_info = next((i for i in res_ch.data if i["id"] == post["channel_id"]), None)
        city = ch_info.get('target_city') if ch_info else "Россия"
        
        print(f"🧐 ИИ анализирует {post['id']} ({city})...")
        ai_data = await process_with_ai(post['text'], city)
        
        if ai_data == "LIMIT_EXCEEDED":
            print("⏸ Лимит исчерпан, прерываем цикл. Остальное в следующий раз.")
            break

        if ai_data:
            supabase.table("eparsed_posts").insert({
                "raw_post_id": post['id'],
                "is_ad": ai_data.get('is_ad', False),
                "json_data": ai_data
            }).execute()

            if ai_data.get('is_ad') is True:
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
                    print(f"⚠️ Ошибка витрины: {e}")

            supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        else:
            supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()
        
        await asyncio.sleep(15) # Безопасная пауза

    await client.disconnect()
    print("🏁 Смена на Заводе завершена.")

if __name__ == "__main__":
    asyncio.run(main())
