import os
import asyncio
import json
import requests
import re
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- НАСТРОЙКИ (GitHub Secrets) ---
API_ID = os.environ.get('TG_API_ID')
API_HASH = os.environ.get('TG_API_HASH')
SESSION_STRING = os.environ.get('TG_SESSION_STRING')
GEMINI_KEY = os.environ.get('GEMINI_KEY')
SUPABASE_URL = os.environ.get('SUPABASEE_URL') 
SUPABASE_KEY = os.environ.get('SUPABASEE_KEY')

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def is_rent_keyword_found(text):
    """Грубое сито: если нет корня 'сда-', не тратим деньги на ИИ"""
    if not text: return False
    keywords = ['сдам', 'сдаю', 'сдается', 'сдаётся', 'сдача', 'пересдам']
    return any(word in text.lower() for word in keywords)

async def process_with_ai(text, city_context):
    """ИИ-Мозг: Фильтрует мусор и структурирует данные"""
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
    print("🚀 Запуск Завода v4.0 (Real-time Edition)")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    # 1. ПОЛУЧАЕМ ПАСПОРТА КАНАЛОВ
    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    
    for ch in res_ch.data:
        # Логика "Курсора": берем сообщения новее, чем те, что уже есть в базе
        last_id = ch.get('last_post_id') or 0
        print(f"📡 Мониторинг {ch['username']} (последний ID в базе: {last_id})")
        
        params = {'limit': 10} # Если канал новый - берем 10 последних для "засева"
        if last_id > 0:
            params = {'min_id': last_id} # Если канал уже в работе - берем только новые (выше ID)

        new_max_id = last_id
        
        async for msg in client.iter_messages(ch['username'], **params):
            if not msg.text: continue
            
            # Запоминаем самый большой ID из новых сообщений
            if msg.id > new_max_id: new_max_id = msg.id

            # Режим фильтрации: AI_ONLY (для вольных) или поиск корня "сда-"
            should_process = (ch['processing_mode'] == 'AI_ONLY' or is_rent_keyword_found(msg.text))
            status = "new" if should_process else "ignored"
            
            # Пишем в RAW таблицу. Сохраняем дату из Telegram.
            supabase.table("eraw_posts").upsert({
                "channel_id": ch['id'],
                "tg_post_id": msg.id,
                "text": msg.text,
                "status": status,
                "created_at": msg.date.isoformat()
            }, on_conflict="channel_id, tg_post_id").execute()

        # Обновляем "закладку" в базе, чтобы в следующий раз не качать это же самое
        if new_max_id > last_id:
            supabase.table("echannels").update({"last_post_id": new_max_id}).eq("id", ch['id']).execute()
            print(f"✅ Канал {ch['username']} обновлен до поста №{new_max_id}")

    # 2. ПЕРЕРАБОТКА ОЧЕРЕДИ (ИИ)
    # Берем пачку новых постов. Без лимита (обработает всё, что успеет за сессию)
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").execute()
    
    for post in res_new.data:
        # Узнаем город из паспорта, чтобы подсказать ИИ контекст
        channel_info = next((i for i in res_ch.data if i["id"] == post["channel_id"]), None)
        city = channel_info.get('target_city', 'Россия') if channel_info else 'Россия'
        
        print(f"🧐 ИИ анализирует пост {post['id']}...")
        ai_data = await process_with_ai(post['text'], city)
        
        if ai_data:
            # А) Вердикт в историю
            supabase.table("eparsed_posts").insert({
                "raw_post_id": post['id'],
                "is_ad": ai_data.get('is_ad', False),
                "json_data": ai_data
            }).execute()

            # Б) На витрину (если ИИ подтвердил лот)
            if ai_data.get('is_ad') is True:
                ch_user = channel_info.get('username', 'channel').replace('@', '')
                
                # Формируем ссылки для интерфейса:
                source_url = f"https://t.me/{ch_user}/{post['tg_post_id']}"
                # Фото-заглушка (виджет Telegram) для отображения на сайте
                main_photo_url = f"https://t.me/{ch_user}/{post['tg_post_id']}?embed=1"

                try:
                    supabase.table("eready_ads").upsert({
                        "raw_post_id": post['id'],
                        "channel_id": post['channel_id'],
                        "deal_type": ai_data.get('deal_type', 'rent'),
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
                    print(f"✅ ДОБАВЛЕНО: {ai_data.get('price_value')} руб. ({source_url})")
                except Exception as e:
                    print(f"⚠️ Ошибка витрины: {e}")

            supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        else:
            supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()
        
        # Твоя проверенная задержка для бесплатного лимита Google
        await asyncio.sleep(15)

    await client.disconnect()
    print("🏁 Смена на Заводе окончена. Все посты обработаны.")

if __name__ == "__main__":
    asyncio.run(main())
