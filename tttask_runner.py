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

def clean_text_by_config(text, config):
    """Пре-фильтр: отсекаем мусор и режем рекламу (БЕСПЛАТНО)"""
    if not text or len(text) < 40:
        return None, "too_short"
    
    t_lower = text.lower()
    filters = config.get('filters', {}) if config else {}
    
    # 1. Стоп-слова (Сниму, Ищу)
    for sw in filters.get('stop_words', []):
        if sw.lower() in t_lower:
            return None, f"stop_word: {sw}"
            
    # 2. Обрезка футера (Рекламы)
    cleaned_text = text
    for fc in filters.get('footer_cutters', []):
        idx = cleaned_text.lower().find(fc.lower())
        if idx != -1:
            cleaned_text = cleaned_text[:idx]
            
    return cleaned_text.strip(), "ok"

async def process_with_ai(text):
    """Золотой стандарт + Контакты + Чистка"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    prompt = f"""
    Верни JSON строго по схеме. Если данных нет - null.
    is_ad: false если это поиск жилья (сниму), реклама услуг или продажа.
    contact_phone: только цифры (79001234567).
    
    {{
      "is_ad": boolean,
      "deal_type": "rent",
      "property_type": "apartment" | "house" | "studio" | "room",
      "price_value": number,
      "rooms": number,
      "area_sqm": number,
      "address_raw": "string",
      "contact_phone": "string",
      "contact_tg": "string"
    }}
    Текст: {text}
    """
    
    try:
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(url, json=payload, timeout=20)
        res_json = resp.json()
        raw_ai_text = res_json['candidates'][0]['content']['parts'][0]['text']
        clean_json = raw_ai_text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except:
        return None

async def main():
    print("🚀 Запуск Умного Завода...")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    # 1. СОБИРАЕМ СЫРЬЕ И ЧИСТИМ
    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    for ch in res_ch.data:
        print(f"📡 Сбор: {ch['username']}")
        config = ch.get('parser_config', {})
        
        async for msg in client.iter_messages(ch['username'], limit=50):
            if not msg.text: continue
            
            # Применяем фильтр
            cleaned, reason = clean_text_by_config(msg.text, config)
            status = "new" if reason == "ok" else "ignored"
            
            supabase.table("eraw_posts").upsert({
                "channel_id": ch['id'],
                "tg_post_id": msg.id,
                "text": msg.text,
                "cleaned_text": cleaned,
                "status": status,
                "ignore_reason": reason if status == "ignored" else None
            }, on_conflict="channel_id, tg_post_id").execute()

    # 2. ОБРАБАТЫВАЕМ ОЧЕРЕДЬ
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").limit(15).execute()
    for post in res_new.data:
        print(f"🧠 ИИ анализирует пост {post['id']}...")
        
        # Передаем только очищенный текст (без рекламы)
        text_to_parse = post['cleaned_text'] if post['cleaned_text'] else post['text']
        ai_data = await process_with_ai(text_to_parse)
        
        if ai_data:
            # А) В eparsed_posts
            supabase.table("eparsed_posts").insert({
                "raw_post_id": post['id'],
                "is_ad": ai_data.get('is_ad', False),
                "json_data": ai_data, # Переименовал payload в json_data согласно твоей новой структуре
                "schema_version": 1
            }).execute()

            # Б) В eready_ads
            if ai_data.get('is_ad'):
                try:
                    supabase.table("eready_ads").upsert({
                        "raw_post_id": post['id'],
                        "channel_id": post['channel_id'],
                        "deal_type": ai_data.get('deal_type'),
                        "property_type": ai_data.get('property_type'),
                        "price_value": ai_data.get('price_value'),
                        "rooms": ai_data.get('rooms'),
                        "area_sqm": ai_data.get('area_sqm'),
                        "address_raw": ai_data.get('address_raw'),
                        "contact_phone": ai_data.get('contact_phone'),
                        "contact_tg": ai_data.get('contact_tg')
                    }, on_conflict="raw_post_id").execute()
                    print(f"✅ Готово: {ai_data.get('price_value')} руб.")
                except Exception as e:
                    print(f"⚠️ Ошибка вставки: {e}")

            supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        else:
            supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()

    await client.disconnect()
    print("🏁 Работа завершена")

if __name__ == "__main__":
    asyncio.run(main())
