import os
import asyncio
import json
import requests
import re
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- НАСТРОЙКИ (Берутся из переменных окружения GitHub) ---
API_ID = os.environ.get('TG_API_ID')
API_HASH = os.environ.get('TG_API_HASH')
SESSION_STRING = os.environ.get('TG_SESSION_STRING')
GEMINI_KEY = os.environ.get('GEMINI_KEY')
SUPABASE_URL = os.environ.get('SUPABASEE_URL') 
SUPABASE_KEY = os.environ.get('SUPABASEE_KEY')

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def clean_text_by_config(text, config):
    """
    УМНЫЙ ФИЛЬТР: 
    1. Сначала режем футер (удаляем хештеги и рекламу).
    2. Потом проверяем на стоп-слова в чистом тексте.
    """
    if not text or len(text) < 40:
        return None, "too_short"
    
    filters = config.get('filters', {}) if config else {}
    
    # --- ШАГ 1: ОБРЕЗАЕМ ФУТЕР (РЕКЛАМУ) ---
    # Это удаляет блоки с хештегами типа #сниму до того, как сработает фильтр
    cleaned_text = text
    for fc in filters.get('footer_cutters', []):
        idx = cleaned_text.lower().find(fc.lower())
        if idx != -1:
            cleaned_text = cleaned_text[:idx]
    
    # Теперь работаем с очищенным текстом в нижнем регистре
    cleaned_lower = cleaned_text.lower()

    # --- ШАГ 2: ПРОВЕРЯЕМ СТОП-СЛОВА (В ОЧИЩЕННОМ ТЕКСТЕ) ---
    for sw in filters.get('stop_words', []):
        if sw.lower() in cleaned_lower:
            # Если стоп-слово найдено в ОСНОВНОМ тексте (а не в хвосте) — игнорируем
            return None, f"stop_word: {sw}"
            
    # --- ШАГ 3: ПРОВЕРКА НА ОБЯЗАТЕЛЬНЫЕ СЛОВА (GO-WORDS) ---
    go_words = filters.get('go_words', [])
    if go_words:
        if not any(gw.lower() in cleaned_lower for gw in go_words):
            return None, "no_go_words_found"

    return cleaned_text.strip(), "ok"

async def process_with_ai(text):
    """Метод через URL-запрос (Gemini 1.5 Flash)"""
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
    Текст объявления:
    {text}
    """
    
    try:
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(url, json=payload, timeout=25)
        res_json = resp.json()
        
        # Извлекаем текст ответа ИИ
        raw_ai_text = res_json['candidates'][0]['content']['parts'][0]['text']
        
        # Чистим JSON от возможных markdown-тегов
        clean_json = raw_ai_text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"⚠️ Ошибка ИИ запроса: {e}")
        return None

async def main():
    print("🚀 Запуск Умного Завода v1.1...")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    # 1. СОБИРАЕМ И ПРЕД-ФИЛЬТРУЕМ
    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    for ch in res_ch.data:
        print(f"📡 Мониторинг канала: {ch['username']}")
        config = ch.get('parser_config', {})
        
        async for msg in client.iter_messages(ch['username'], limit=50):
            if not msg.text: continue
            
            # Применяем хирургическую очистку и фильтр
            cleaned, reason = clean_text_by_config(msg.text, config)
            status = "new" if reason == "ok" else "ignored"
            
            # Записываем в базу
            supabase.table("eraw_posts").upsert({
                "channel_id": ch['id'],
                "tg_post_id": msg.id,
                "text": msg.text,
                "cleaned_text": cleaned,
                "status": status,
                "ignore_reason": reason if status == "ignored" else None
            }, on_conflict="channel_id, tg_post_id").execute()

    # 2. ПЕРЕРАБОТКА (ИИ-ПАРСИНГ)
    # Берем пачку постов, которые прошли фильтр (status='new')
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").limit(15).execute()
    
    for post in res_new.data:
        print(f"🧠 ИИ анализирует пост {post['id']}...")
        
        # Посылаем ИИ уже ОЧИЩЕННЫЙ текст (без рекламы и хештегов)
        text_to_parse = post['cleaned_text'] if post['cleaned_text'] else post['text']
        
        ai_data = await process_with_ai(text_to_parse)
        
        if ai_data:
            # А) Сохраняем полный результат разбора
            supabase.table("eparsed_posts").insert({
                "raw_post_id": post['id'],
                "is_ad": ai_data.get('is_ad', False),
                "json_data": ai_data,
                "schema_version": 1
            }).execute()

            # Б) Если ИИ подтвердил, что это сдача квартиры — в витрину
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
                    print(f"✅ Готово: {ai_data.get('price_value')} руб. в БД.")
                except Exception as e:
                    print(f"⚠️ Ошибка вставки в ready_ads: {e}")

            # Меняем статус на 'parsed'
            supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        else:
            # Если ИИ не ответил или ошибка JSON
            supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()

    await client.disconnect()
    print("🏁 Работа завершена.")

if __name__ == "__main__":
    asyncio.run(main())
