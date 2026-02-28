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
    """Простое сито: корень 'сда-'"""
    if not text: return False
    keywords = ['сдам', 'сдаю', 'сдается', 'сдаётся', 'сдача', 'пересдам']
    t_lower = text.lower()
    return any(word in t_lower for word in keywords)

async def process_with_ai(text, city_context):
    """Твой рабочий метод запроса к Gemini 2.0"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}"
    
    prompt = f"""
    Верни JSON строго по схеме. Если данных нет - null.
    is_ad: true только если это ПРЕДЛОЖЕНИЕ аренды жилья в г. {city_context}. 
    rooms: Для "room" и "studio" всегда 1. Для "apartment" - реальное кол-во.

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
    print("🚀 Запуск Завода v4.2")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    total_collected = 0
    total_ai_processed = 0

    # 1. СБОР НОВЫХ ПОСТОВ
    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    
    for ch in res_ch.data:
        last_id = ch.get('last_post_id') or 0
        print(f"📡 Канал {ch['username']} (last_id: {last_id})")
        
        # Если 0 - берем последние 10, если есть ID - берем всё что новее (min_id)
        params = {'limit': 10} if last_id == 0 else {'min_id': last_id}
        current_channel_new_posts = 0
        max_id_in_run = last_id

        async for msg in client.iter_messages(ch['username'], **params):
            if not msg.text: continue
            if msg.id > max_id_in_run: max_id_in_run = msg.id

            # Проверка режима (AI_ONLY или фильтр "сдам")
            should_process = (ch['processing_mode'] == 'AI_ONLY' or is_rent_keyword_found(msg.text))
            status = "new" if should_process else "ignored"
            
            supabase.table("eraw_posts").upsert({
                "channel_id": ch['id'],
                "tg_post_id": msg.id,
                "text": msg.text,
                "status": status,
                "created_at": msg.date.isoformat()
            }, on_conflict="channel_id, tg_post_id").execute()
            
            current_channel_new_posts += 1
            total_collected += 1

        # Обновляем "закладку" в канале
        if max_id_in_run > last_id:
            supabase.table("echannels").update({"last_post_id": max_id_in_run}).eq("id", ch['id']).execute()
            print(f"📥 Собрано {current_channel_new_posts} новых сообщений")

    # 2. ОБРАБОТКА ОЧЕРЕДИ
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").execute()
    print(f"🧠 Начинаем анализ {len(res_new.data)} постов...")

    for post in res_new.data:
        ch_info = next((i for i in res_ch.data if i["id"] == post["channel_id"]), None)
        city = ch_info.get('target_city', 'Россия') if ch_info else 'Россия'
        
        print(f"🧐 Обработка поста {post['id']}...")
        ai_data = await process_with_ai(post['text'], city)
        
        if ai_data:
            # Пишем вердикт
            supabase.table("eparsed_posts").insert({
                "raw_post_id": post['id'], 
                "is_ad": ai_data.get('is_ad', False), 
                "json_data": ai_data
            }).execute()

            if ai_data.get('is_ad'):
                # Генерируем ссылки
                username = ch_info['username'].replace('@', '')
                source_url = f"https://t.me/{username}/{post['tg_post_id']}"
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
                    print(f"✅ Готово: {ai_data.get('price_value')} руб.")
                except: pass

            supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
            total_ai_processed += 1
        else:
            supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()
        
        await asyncio.sleep(12) # Твоя рабочая пауза

    await client.disconnect()
    print(f"\n🏁 ИТОГО ЗА СМЕНУ:")
    print(f"📦 Собрано из Telegram: {total_collected}")
    print(f"💎 Обработано ИИ: {total_ai_processed}")

if __name__ == "__main__":
    asyncio.run(main())
