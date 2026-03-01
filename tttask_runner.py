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

# УСТАНАВЛИВАЕМ ТЕСТОВУЮ ДАТУ
TEST_DAY = datetime(2026, 2, 28, tzinfo=timezone.utc)

def is_rent_keyword_found(text):
    """Грубое сито: если нет корня 'сда-', не тратим деньги на ИИ"""
    if not text: return False
    keywords = ['сдам', 'сдаю', 'сдается', 'сдаётся', 'сдача']
    return any(word in text.lower() for word in keywords)

async def process_with_ai(text, city_context):
    """ИИ-Мозг: Анализирует ТЕКСТ. Фото не шлем — экономим 90% бюджета."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}"
    
    prompt = f"""
    Верни JSON строго по схеме. Если данных нет - null.
    is_ad: true только если это ПРЕДЛОЖЕНИЕ аренды жилья в г. {city_context}. 
    {{
      "is_ad": boolean,
      "deal_type": "rent",
      "property_type": "apartment" | "room" | "studio" | "house",
      "price_value": number,
      "deposit_value": number,
      "rooms": number,
      "area_sqm": number,
      "address_raw": "string",
      "contact_phone": "79...",
      "contact_tg": "username"
    }}
    Текст: {text}
    """
    
    try:
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(url, json=payload, timeout=25)
        res_json = resp.json()
        raw_ai_text = res_json['candidates'][0]['content']['parts'][0]['text']
        clean_json = raw_ai_text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except:
        return None

async def main():
    print(f"🚀 ТЕСТОВЫЙ ЗАПУСК за дату: {TEST_DAY.date()}")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    
    for ch in res_ch.data:
        print(f"📡 Канал {ch['username']}: поиск постов за 28 февраля...")
        
        # Начинаем поиск с 1 марта и идем назад в прошлое
        async for msg in client.iter_messages(ch['username'], offset_date=TEST_DAY + timedelta(days=1), limit=100):
            # Если ушли глубже 28-го февраля (в 27-е) — стоп
            if msg.date.date() < TEST_DAY.date():
                break
            
            # Если пост из будущего (редко, но бывает) — пропускаем
            if msg.date.date() > TEST_DAY.date():
                continue

            # ГЛАВНОЕ ПРАВИЛО: Нет текста — нет объявления. 
            # Это автоматически отсекает пустые фото из альбомов.
            if not msg.text: 
                continue

            # Фильтрация режима
            should_process = (ch['processing_mode'] == 'AI_ONLY' or is_rent_keyword_found(msg.text))
            status = "new" if should_process else "ignored"
            
            # Сохраняем в RAW
            supabase.table("eraw_posts").upsert({
                "channel_id": ch['id'],
                "tg_post_id": msg.id,
                "text": msg.text,
                "status": status,
                "created_at": msg.date.isoformat()
            }, on_conflict="channel_id, tg_post_id").execute()

    # 2. ОБРАБОТКА ОЧЕРЕДИ
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").execute()
    print(f"🧠 Найдено {len(res_new.data)} потенциальных объявлений за 28.02")

    for post in res_new.data:
        ch_info = next((i for i in res_ch.data if i["id"] == post["channel_id"]), None)
        city = ch_info.get('target_city', 'Россия') if ch_info else 'Россия'
        
        print(f"🧐 Анализ поста {post['id']}...")
        ai_data = await process_with_ai(post['text'], city)
        
        if ai_data and ai_data.get('is_ad'):
            # Ссылки на ТГ и Фото-виджет
            ch_user = ch_info['username'].replace('@', '')
            source_url = f"https://t.me/{ch_user}/{post['tg_post_id']}"
            main_photo_url = f"{source_url}?embed=1"

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
                print(f"✅ ПРИНЯТО: {ai_data.get('price_value')} руб.")
            except: pass

        supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        await asyncio.sleep(12) # Пауза для лимита Google

    await client.disconnect()
    print(f"🏁 Тест за 28.02 завершен.")

if __name__ == "__main__":
    asyncio.run(main())
