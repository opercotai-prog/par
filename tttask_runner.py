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

# Твоя рабочая дата
TARGET_DATE = datetime(2026, 2, 17, tzinfo=timezone.utc)

def is_rent_keyword_found(text):
    if not text: return False
    keywords = ['сдам', 'сдаю', 'сдается', 'сдаётся', 'сдаем', 'сдача']
    t_lower = text.lower()
    return any(word in t_lower for word in keywords)

async def upload_photo_to_supabase(client, message, file_name):
    """Твоя рабочая функция фото"""
    try:
        if not message.photo: return None
        photo_bytes = await client.download_media(message.photo, file=bytes)
        storage_path = f"ads/{file_name}.jpg"
        supabase.storage.from_('post_photos').upload(
            path=storage_path, file=photo_bytes,
            file_options={"content-type": "image/jpeg", "x-upsert": "true"}
        )
        return supabase.storage.from_('post_photos').get_public_url(storage_path)
    except Exception as e:
        print(f"⚠️ Ошибка Storage: {e}")
        return None

async def process_with_ai(text, city_context):
    """Твой рабочий ИИ-парсер Gemini 2.5-flash"""
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
    Правила: rooms всегда 1 для studio/room. Текст: {text}
    """
    try:
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(url, json=payload, timeout=30)
        res_json = resp.json()
        raw_ai_text = res_json['candidates'][0]['content']['parts'][0]['text']
        clean_json = re.sub(r'```json|```', '', raw_ai_text).strip()
        return json.loads(clean_json)
    except: return None

async def main():
    print(f"🚀 Запуск Завода 5.0. Цель: {TARGET_DATE.date()}")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    # --- ЭТАП 1: ПЫЛЕСОС (Сбор в estream_raw) ---
    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    for ch in res_ch.data:
        print(f"📡 Пылесосим: {ch['username']}")
        async for msg in client.iter_messages(ch['username'], offset_date=TARGET_DATE + timedelta(days=1), limit=100):
            if msg.date.date() < TARGET_DATE.date(): break
            if msg.date.date() > TARGET_DATE.date(): continue
            if not msg.text: continue

            # Просто сохраняем всё сырье без разбора
            supabase.table("estream_raw").upsert({
                "source_name": ch['username'],
                "external_id": msg.id,
                "raw_text": msg.text,
                "created_at": msg.date.isoformat()
            }, on_conflict="source_name, external_id").execute()

    # --- ЭТАП 2: СОРТИРОВКА (Из estream_raw в eraw_posts) ---
    # Берем необработанное из буфера
    res_stream = supabase.table("estream_raw").select("*").eq("status", "new").execute()
    print(f"🚜 Сортировка: {len(res_stream.data)} постов...")
    
    for entry in res_stream.data:
        # Находим инфо о канале
        ch = next((c for c in res_ch.data if c['username'] == entry['source_name']), None)
        if not ch: continue

        # Логика режима (AI_ONLY или фильтр слов)
        should_process = (ch['processing_mode'] == 'AI_ONLY' or is_rent_keyword_found(entry['raw_text']))
        status = "new" if should_process else "ignored"
        
        # Получаем объект сообщения для загрузки фото (Telethon)
        msg_obj = await client.get_messages(ch['username'], ids=entry['external_id'])
        photo_url = await upload_photo_to_supabase(client, msg_obj, f"{ch['id']}_{entry['external_id']}") if msg_obj and msg_obj.photo else None

        # Перекладываем в основную таблицу RAW
        supabase.table("eraw_posts").upsert({
            "channel_id": ch['id'],
            "tg_post_id": entry['external_id'],
            "text": entry['raw_text'],
            "status": status,
            "created_at": entry['created_at'],
            "media_info": {"photo_url": photo_url} if photo_url else []
        }, on_conflict="channel_id, tg_post_id").execute()

        # Помечаем в буфере, что работа закончена
        supabase.table("estream_raw").update({"status": "done"}).eq("id", entry['id']).execute()

    # --- ЭТАП 3: ЦЕХ ПЕРЕРАБОТКИ (ИИ) ---
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").execute()
    print(f"🧠 ИИ-анализ очереди: {len(res_new.data)} объектов...")

    for post in res_new.data:
        ch_info = next((i for i in res_ch.data if i["id"] == post["channel_id"]), None)
        city = ch_info.get('target_city', 'Россия') if ch_info else 'Россия'
        
        ai_data = await process_with_ai(post['text'], city)
        
        if ai_data:
            supabase.table("eparsed_posts").insert({
                "raw_post_id": post['id'], "is_ad": ai_data.get('is_ad', False), "json_data": ai_data
            }).execute()

            if ai_data.get('is_ad') is True:
                ch_user = ch_info['username'].replace('@', '')
                source_url = f"https://t.me/{ch_user}/{post['tg_post_id']}"
                local_photo = post.get('media_info', {}).get('photo_url') if isinstance(post.get('media_info'), dict) else None

                supabase.table("eready_ads").upsert({
                    "raw_post_id": post['id'], "channel_id": post['channel_id'],
                    "deal_type": "rent", "property_type": ai_data.get('property_type'),
                    "price_value": ai_data.get('price_value'), "deposit_value": ai_data.get('deposit_value'),
                    "rooms": ai_data.get('rooms'), "area_sqm": ai_data.get('area_sqm'),
                    "address_raw": ai_data.get('address_raw'), "contact_phone": ai_data.get('contact_phone'),
                    "contact_tg": ai_data.get('contact_tg'), "source_url": source_url,
                    "main_photo_url": local_photo or f"{source_url}?embed=1"
                }, on_conflict="raw_post_id").execute()
                print(f"✅ Готово: {ai_data.get('price_value')} руб.")

            supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        else:
            supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()
            
        await asyncio.sleep(12) # Твоя задержка

    await client.disconnect()
    print("🏁 Смена закончена.")

if __name__ == "__main__":
    asyncio.run(main())
