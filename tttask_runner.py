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
TARGET_DATE = datetime(2026, 3, 7, tzinfo=timezone.utc)

def is_rent_keyword_found(text):
    if not text: return False
    keywords = ['сдам', 'сдаю', 'сдается', 'сдаётся', 'сдаем', 'сдача']
    t_lower = text.lower()
    return any(word in t_lower for word in keywords)

async def upload_album_to_supabase(client, messages, channel_id):
    """Профессиональная склейка: скачивает ВСЕ фото альбома"""
    photo_urls = []
    for msg in messages:
        if not msg or not msg.photo: continue
        try:
            photo_bytes = await client.download_media(msg.photo, file=bytes)
            # Уникальное имя: ID_канала + ID_сообщения
            storage_path = f"ads/{channel_id}_{msg.id}.jpg"
            supabase.storage.from_('post_photos').upload(
                path=storage_path, file=photo_bytes,
                file_options={"content-type": "image/jpeg", "x-upsert": "true"}
            )
            url = supabase.storage.from_('post_photos').get_public_url(storage_path)
            photo_urls.append(url)
        except: pass
    return photo_urls

async def process_with_ai(text, city_context):
    """ВОССТАНОВЛЕННЫЙ 'ЗОЛОТОЙ' ПРОМПТ ИЗ V3.8"""
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
    
    Правила:
    1. rooms: если studio или room — всегда 1. Если квартира — реальное число.
    2. price_value: только число, без текста.
    3. property_type: строго один из списка.
    
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
        if 'candidates' not in res_json: return None
        raw_ai_text = res_json['candidates'][0]['content']['parts'][0]['text']
        clean_json = raw_ai_text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except: return None

async def main():
    print(f"🚀 Завод v5.4. (Восстановленный промпт). Цель: {TARGET_DATE.date()}")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    # --- ЭТАП 1: ПЫЛЕСОС ---
    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    for ch in res_ch.data:
        print(f"📡 Сбор: {ch['username']}")
        async for msg in client.iter_messages(ch['username'], offset_date=TARGET_DATE + timedelta(days=1), limit=100):
            if msg.date.date() < TARGET_DATE.date(): break
            if msg.date.date() > TARGET_DATE.date(): continue
            if not msg.text: continue

            supabase.table("estream_raw").upsert({
                "source_name": ch['username'],
                "external_id": msg.id,
                "raw_text": msg.text,
                "created_at": msg.date.isoformat()
            }, on_conflict="source_name, external_id").execute()

    # --- ЭТАП 2: СОРТИРОВКА ---
    res_stream = supabase.table("estream_raw").select("*").eq("status", "new").execute()
    for entry in res_stream.data:
        ch = next((c for c in res_ch.data if c['username'] == entry['source_name']), None)
        if not ch: continue
        
        should_process = (ch['processing_mode'] == 'AI_ONLY' or is_rent_keyword_found(entry['raw_text']))
        status = "new" if should_process else "ignored"
        
        supabase.table("eraw_posts").upsert({
            "channel_id": ch['id'], "tg_post_id": entry['external_id'],
            "text": entry['raw_text'], "status": status, "created_at": entry['created_at']
        }, on_conflict="channel_id, tg_post_id").execute()
        supabase.table("estream_raw").update({"status": "done"}).eq("id", entry['id']).execute()

    # --- ЭТАП 3: ПАРСИНГ + ФОТО ---
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").execute()
    print(f"🧠 В очереди: {len(res_new.data)}")

    for post in res_new.data:
        ch_info = next((i for i in res_ch.data if i["id"] == post["channel_id"]), None)
        city = ch_info.get('target_city', 'Россия') if ch_info else 'Россия'
        
        print(f"🧐 ИИ анализирует пост {post['id']}...")
        ai_data = await process_with_ai(post['text'], city)
        
        if ai_data:
            # Всегда пишем вердикт
            supabase.table("eparsed_posts").insert({
                "raw_post_id": post['id'], "is_ad": ai_data.get('is_ad', False), "json_data": ai_data
            }).execute()

            if ai_data.get('is_ad') is True:
                # 1. Склеиваем альбом (сканируем +- 10 ID вокруг)
                main_msg = await client.get_messages(ch_info['username'], ids=post['tg_post_id'])
                album_messages = [main_msg]
                if main_msg and main_msg.grouped_id:
                    search_scope = await client.get_messages(ch_info['username'], min_id=main_msg.id-10, max_id=main_msg.id+10)
                    album_messages = [m for m in search_scope if m.grouped_id == main_msg.grouped_id]
                
                # Загружаем галерею
                all_photos = await upload_album_to_supabase(client, album_messages, post['channel_id'])
                
                # 2. На витрину
                ch_user = ch_info['username'].replace('@', '')
                source_url = f"https://t.me/{ch_user}/{post['tg_post_id']}"
                
                try:
                    supabase.table("eready_ads").upsert({
                        "raw_post_id": post['id'], "channel_id": post['channel_id'],
                        "deal_type": "rent", "property_type": ai_data.get('property_type'),
                        "price_value": ai_data.get('price_value'), "deposit_value": ai_data.get('deposit_value'),
                        "rooms": ai_data.get('rooms'), "area_sqm": ai_data.get('area_sqm'),
                        "address_raw": ai_data.get('address_raw'), "contact_phone": ai_data.get('contact_phone'),
                        "contact_tg": ai_data.get('contact_tg'), "source_url": source_url,
                        "main_photo_url": all_photos[0] if all_photos else f"{source_url}?embed=1",
                        "photos": all_photos
                    }, on_conflict="raw_post_id").execute()
                    print(f"✅ ПРИНЯТО: {ai_data.get('price_value')} руб. ({len(all_photos)} фото)")
                except Exception as e: print(f"⚠️ Ошибка вставки: {e}")
            else:
                print(f"❌ ОТКЛОНЕНО (мусор)")

            supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        else:
            supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()
            print(f"⚠️ ОШИБКА: ИИ не ответил")
            
        await asyncio.sleep(12) 

    await client.disconnect()
    print("🏁 Работа завершена.")

if __name__ == "__main__":
    asyncio.run(main())
