import os
import asyncio
import json
import requests
import re
import io
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

def is_rent_keyword_found(text):
    """Базовый фильтр для режима FILTER_FIRST"""
    if not text: return False
    keywords = ['сдам', 'сдаю', 'сдается', 'сдаётся', 'сдача', 'пересдам']
    t_lower = text.lower()
    return any(word in t_lower for word in keywords)

async def upload_photo_to_supabase(client, message, file_name):
    """Скачивает фото из Telegram и загружает в Supabase Storage"""
    try:
        if not message.photo: return None
        photo_bytes = await client.download_media(message.photo, file=bytes)
        storage_path = f"ads/{file_name}.jpg"
        supabase.storage.from_('post_photos').upload(
            path=storage_path,
            file=photo_bytes,
            file_options={"content-type": "image/jpeg", "x-upsert": "true"}
        )
        return supabase.storage.from_('post_photos').get_public_url(storage_path)
    except Exception as e:
        print(f"⚠️ Ошибка Storage: {e}")
        return None

async def process_with_ai(text, city_context):
    """ИИ-Парсер на модели 2.5-flash"""
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
    2. Если данных нет - null.
    
    Текст: {text}
    """
    
    try:
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(url, json=payload, timeout=30)
        res_json = resp.json()
        
        if 'error' in res_json:
            print(f"❌ Ошибка Gemini API: {res_json['error']['message']}")
            return None
            
        raw_ai_text = res_json['candidates'][0]['content']['parts'][0]['text']
        clean_json = re.sub(r'```json|```', '', raw_ai_text).strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"⚠️ Ошибка парсинга JSON: {e}")
        return None

async def main():
    print("🚀 Запуск Завода v4.0 (Real-time)")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    # 1. ПОЛУЧАЕМ ПАСПОРТА КАНАЛОВ
    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    
    for ch in res_ch.data:
        last_id = ch.get('last_post_id') or 0
        print(f"📡 Канал: {ch['username']} (указатель: {last_id})")
        
        # Если last_id=0 — берем последние 10 (засев). Иначе — всё что НОВЕЕ (min_id)
        params = {'limit': 10} if last_id == 0 else {'min_id': last_id}
        max_id_seen = last_id

        async for msg in client.iter_messages(ch['username'], **params):
            if not msg.text: continue
            if msg.id > max_id_seen: max_id_seen = msg.id

            # Логика фильтрации
            should_process = (ch['processing_mode'] == 'AI_ONLY' or is_rent_keyword_found(msg.text))
            status = "new" if should_process else "ignored"
            
            # Загрузка фото
            photo_url = None
            if status == "new" and msg.photo:
                photo_url = await upload_photo_to_supabase(client, msg, f"{ch['id']}_{msg.id}")

            # Сохраняем в RAW
            supabase.table("eraw_posts").upsert({
                "channel_id": ch['id'],
                "tg_post_id": msg.id,
                "text": msg.text,
                "status": status,
                "created_at": msg.date.isoformat(),
                "media_info": {"photo_url": photo_url} if photo_url else []
            }, on_conflict="channel_id, tg_post_id").execute()

        # Обновляем указатель в базе
        if max_id_seen > last_id:
            supabase.table("echannels").update({"last_post_id": max_id_seen}).eq("id", ch['id']).execute()

    # 2. ОБРАБОТКА ОЧЕРЕДИ
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").execute()
    print(f"🧐 В очереди на ИИ: {len(res_new.data)} постов")

    for post in res_new.data:
        channel_info = next((i for i in res_ch.data if i["id"] == post["channel_id"]), None)
        city = channel_info.get('target_city', 'Россия') if channel_info else 'Россия'
        
        print(f"🧠 ИИ анализирует пост {post['id']}...")
        ai_data = await process_with_ai(post['text'], city)
        
        if ai_data:
            supabase.table("eparsed_posts").insert({
                "raw_post_id": post['id'],
                "is_ad": ai_data.get('is_ad', False),
                "json_data": ai_data
            }).execute()

            if ai_data.get('is_ad'):
                username = channel_info.get('username', 'channel').replace('@', '')
                source_url = f"https://t.me/{username}/{post['tg_post_id']}"
                local_photo = post.get('media_info', {}).get('photo_url') if isinstance(post.get('media_info'), dict) else None

                try:
                    supabase.table("eready_ads").upsert({
                        "raw_post_id": post['id'],
                        "channel_id": post['channel_id'],
                        "deal_type": ai_data.get('deal_type', 'rent'), # ПОЧИНИЛИ deal_type
                        "property_type": ai_data.get('property_type'),
                        "price_value": ai_data.get('price_value'),
                        "deposit_value": ai_data.get('deposit_value'),
                        "rooms": ai_data.get('rooms'),
                        "area_sqm": ai_data.get('area_sqm'),
                        "address_raw": ai_data.get('address_raw'),
                        "contact_phone": ai_data.get('contact_phone'),
                        "contact_tg": ai_data.get('contact_tg'),
                        "source_url": source_url,
                        "main_photo_url": local_photo or f"{source_url}?embed=1"
                    }, on_conflict="raw_post_id").execute()
                    print(f"✅ Готово: {ai_data.get('price_value')} руб.")
                except Exception as e:
                    print(f"⚠️ Ошибка витрины: {e}")

            supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        else:
            supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()
            
        await asyncio.sleep(12)

    await client.disconnect()
    print("🏁 Работа завершена.")

if __name__ == "__main__":
    asyncio.run(main())
