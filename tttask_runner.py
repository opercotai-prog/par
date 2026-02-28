import os
import asyncio
import json
import requests
import re
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
    """Грубое сито для режима FILTER_FIRST"""
    if not text: return False
    keywords = ['сдам', 'сдаю', 'сдается', 'сдаётся', 'сдача', 'пересдам']
    return any(word in text.lower() for word in keywords)

async def upload_photo_to_supabase(client, message, file_name):
    """Скачивает фото из ТГ и шлет в Supabase Storage"""
    try:
        if not message.photo: return None
        photo_bytes = await client.download_media(message.photo, file=bytes)
        storage_path = f"ads/{file_name}.jpg"
        # Бакет должен называться 'post_photos'
        supabase.storage.from_('post_photos').upload(
            path=storage_path,
            file=photo_bytes,
            file_options={"content-type": "image/jpeg", "x-upsert": "true"}
        )
        return supabase.storage.from_('post_photos').get_public_url(storage_path)
    except Exception as e:
        print(f"⚠️ Storage Log: {e}")
        return None

async def process_with_ai(text, city_context):
    """ИИ-Парсер: Бронебойный захват JSON + Gemini 2.0"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}"
    
    prompt = f"""
    Верни JSON строго по схеме. Если данных нет - null.
    is_ad: true только если это ПРЕДЛОЖЕНИЕ аренды жилья в г. {city_context}. 
    rooms: Для "room" и "studio" всегда 1. Для "apartment" - реальное кол-во.

    {{
      "is_ad": boolean,
      "property_type": "apartment" | "room" | "studio" | "house" | "coliving",
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
    
    safety_settings = [
        {"category": c, "threshold": "BLOCK_NONE"} 
        for c in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_DANGEROUS_CONTENT", "HARM_CATEGORY_SEXUALLY_EXPLICIT"]
    ]

    try:
        payload = {"contents": [{"parts": [{"text": prompt}]}], "safetySettings": safety_settings}
        resp = requests.post(url, json=payload, timeout=25)
        res_json = resp.json()

        if 'candidates' not in res_json:
            print(f"⚠️ Gemini Safety/Quota: {res_json}")
            return None

        raw_ai_text = res_json['candidates'][0]['content']['parts'][0]['text']
        # Поиск JSON через Regex (самый надежный метод)
        match = re.search(r'\{.*\}', raw_ai_text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return None
    except Exception as e:
        print(f"⚠️ Ошибка ИИ: {e}")
        return None

async def main():
    print("🚀 Запуск Завода v4.1 (Leader Edition)")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    # 1. СБОР И АВТО-ЗАСЕВ
    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    
    for ch in res_ch.data:
        last_id = ch.get('last_post_id') or 0
        print(f"📡 Канал {ch['username']} (указатель: {last_id})")
        
        params = {'limit': 10} if last_id == 0 else {'min_id': last_id}
        new_max_id = last_id
        
        async for msg in client.iter_messages(ch['username'], **params):
            if not msg.text: continue
            if msg.id > new_max_id: new_max_id = msg.id

            # Фото логика
            photo_url = None
            if msg.photo:
                photo_url = await upload_photo_to_supabase(client, msg, f"{ch['id']}_{msg.id}")

            should_process = (ch['processing_mode'] == 'AI_ONLY' or is_rent_keyword_found(msg.text))
            
            supabase.table("eraw_posts").upsert({
                "channel_id": ch['id'],
                "tg_post_id": msg.id,
                "text": msg.text,
                "status": "new" if should_process else "ignored",
                "created_at": msg.date.isoformat(),
                "media_info": {"photo_url": photo_url} if photo_url else []
            }, on_conflict="channel_id, tg_post_id").execute()

        if new_max_id > last_id:
            supabase.table("echannels").update({"last_post_id": new_max_id}).eq("id", ch['id']).execute()

    # 2. ПЕРЕРАБОТКА (ИИ)
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").execute()
    print(f"🧐 В очереди {len(res_new.data)} постов...")

    for post in res_new.data:
        ch_info = next((i for i in res_ch.data if i["id"] == post["channel_id"]), None)
        city = ch_info.get('target_city', 'Россия') if ch_info else 'Россия'
        
        print(f"🧠 Анализ {post['id']}...")
        ai_data = await process_with_ai(post['text'], city)
        
        if ai_data:
            supabase.table("eparsed_posts").insert({"raw_post_id": post['id'], "is_ad": ai_data.get('is_ad', False), "json_data": ai_data}).execute()

            if ai_data.get('is_ad'):
                ch_user = ch_info.get('username', 'channel').replace('@', '')
                source_url = f"https://t.me/{ch_user}/{post['tg_post_id']}"
                
                # Приоритет: 1. Наше загруженное фото, 2. Ссылка-виджет
                local_photo = post.get('media_info', {}).get('photo_url') if isinstance(post.get('media_info'), dict) else None
                
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
                    "main_photo_url": local_photo or f"{source_url}?embed=1"
                }, on_conflict="raw_post_id").execute()
                print(f"✅ ПРИНЯТО: {ai_data.get('price_value')} руб.")

            supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        else:
            supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()
        
        await asyncio.sleep(15)

    await client.disconnect()
    print("🏁 Смена окончена.")

if __name__ == "__main__":
    asyncio.run(main())
