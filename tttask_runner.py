import os
import asyncio
import json
import requests
import re
import io
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
TARGET_DATE = datetime(2026, 2, 17, tzinfo=timezone.utc)

def is_rent_keyword_found(text):
    if not text: return False
    keywords = ['сдам', 'сдаю', 'сдается', 'сдаётся', 'сдаем', 'сдача']
    t_lower = text.lower()
    return any(word in t_lower for word in keywords)

async def upload_photo_to_supabase(client, message, file_name):
    """Скачивает фото из TG и загружает в Supabase Storage"""
    try:
        if not message.photo:
            return None
        
        # Скачиваем фото в байтовый поток (в память)
        photo_bytes = await client.download_media(message.photo, file=bytes)
        
        # Загружаем в бакет 'post_photos'
        storage_path = f"ads/{file_name}.jpg"
        supabase.storage.from_('post_photos').upload(
            path=storage_path,
            file=photo_bytes,
            file_options={"content-type": "image/jpeg"}
        )
        
        # Получаем публичную ссылку
        public_url = supabase.storage.from_('post_photos').get_public_url(storage_path)
        return public_url
    except Exception as e:
        print(f"⚠️ Ошибка загрузки фото: {e}")
        return None

async def process_with_ai(text, city_context):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    prompt = f"Ты — модератор недвижимости в г. {city_context}. Проанализируй текст. Если это СДАЧА жилья — вытяни JSON. Иначе 'is_ad': false. Текст: {text}"
    # (Здесь остается твоя полная структура JSON из предыдущего скрипта)
    # ... сокращено для краткости ...
    try:
        # Твой стандартный запрос к Gemini
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(url, json=payload, timeout=30)
        raw_ai_text = resp.json()['candidates'][0]['content']['parts'][0]['text']
        clean_json = raw_ai_text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except: return None

async def main():
    print(f"🚀 Запуск Завода с фотофиксацией. Цель: {TARGET_DATE.date()}")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    
    for ch in res_ch.data:
        print(f"📡 Канал: {ch['username']}")
        
        async for msg in client.iter_messages(ch['username'], offset_date=TARGET_DATE + timedelta(days=1), limit=100):
            if msg.date.date() < TARGET_DATE.date(): break 
            if msg.date.date() > TARGET_DATE.date(): continue 
            if not msg.text: continue

            # ЛОГИКА ФОТО: Если в сообщении есть фото, загружаем его сразу
            photo_url = None
            if msg.photo:
                print(f"📸 Загрузка фото для поста {msg.id}...")
                unique_name = f"{ch['id']}_{msg.id}"
                photo_url = await upload_photo_to_supabase(client, msg, unique_name)

            should_process = (ch['processing_mode'] == 'AI_ONLY') or is_rent_keyword_found(msg.text)
            status = "new" if should_process else "ignored"
            
            # Сохраняем в сырье вместе со ссылкой на наше облако
            supabase.table("eraw_posts").upsert({
                "channel_id": ch['id'],
                "tg_post_id": msg.id,
                "text": msg.text,
                "status": status,
                "created_at": msg.date.isoformat(),
                "media_info": {"photo_url": photo_url} if photo_url else []
            }, on_conflict="channel_id, tg_post_id").execute()

    # 2. ОБРАБОТКА ОЧЕРЕДИ
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").execute()
    
    for post in res_new.data:
        channel_info = next((item for item in res_ch.data if item["id"] == post["channel_id"]), None)
        city = channel_info.get('target_city', 'Россия') if channel_info else 'Россия'
        
        ai_data = await process_with_ai(post['text'], city)
        
        if ai_data and ai_data.get('is_ad') is True:
            # Берем фото из media_info, которое мы сохранили на шаге 1
            local_photo = post.get('media_info', {}).get('photo_url') if isinstance(post.get('media_info'), dict) else None
            
            ch_user = channel_info.get('username', 'channel').replace('@', '')
            source_url = f"https://t.me/{ch_user}/{post['tg_post_id']}"

            supabase.table("eready_ads").upsert({
                "raw_post_id": post['id'],
                "channel_id": post['channel_id'],
                "property_type": ai_data.get('property_type'),
                "price_value": ai_data.get('price_value'),
                "address_raw": ai_data.get('address_raw'),
                "contact_tg": ai_data.get('contact_tg'),
                "source_url": source_url,
                "main_photo_url": local_photo or f"{source_url}?embed=1" # Если нашего фото нет, оставим эмбед
            }, on_conflict="raw_post_id").execute()
            print(f"✅ Готово с фото: {ai_data.get('property_type')}")

        supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        await asyncio.sleep(12)

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
