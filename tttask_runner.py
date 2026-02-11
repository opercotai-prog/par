import asyncio
import os
import json
import re
from telethon import TelegramClient
from supabase import create_client, Client
import google.generativeai as genai

# --- НАСТРОЙКИ ---
TELEGRAM_API_ID = os.environ.get("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH")
TELEGRAM_SESSION = os.environ.get("TELEGRAM_SESSION")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Инициализация клиентов
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

def clean_text_by_config(text, config):
    """Умная фильтрация и обрезка текста по паспорту канала"""
    if not text or len(text) < 50:
        return None, "too_short_or_empty"
    
    t_lower = text.lower()
    filters = config.get('filters', {})
    
    # 1. Проверка стоп-слов (Черный список)
    for sw in filters.get('stop_words', []):
        if sw.lower() in t_lower:
            return None, f"stop_word_detected: {sw}"
            
    # 2. Проверка обязательных слов (Белый список)
    go_words = filters.get('go_words', [])
    if go_words:
        if not any(gw.lower() in t_lower for gw in go_words):
            return None, "no_go_words_found"

    # 3. Обрезка футера (Рекламного хвоста)
    cleaned_text = text
    for fc in filters.get('footer_cutters', []):
        idx = cleaned_text.lower().find(fc.lower())
        if idx != -1:
            cleaned_text = cleaned_text[:idx] # Режем всё, что после маркера
            
    return cleaned_text.strip(), "ok"

async def process_with_ai(raw_text):
    """Отправка очищенного текста в Gemini для получения JSON"""
    prompt = f"""
    Ты — эксперт по парсингу недвижимости. 
    Твоя задача: превратить текст в строгий JSON.
    Если это НЕ объявление о сдаче жилья — поставь is_ad: false.
    Если это продажа или коммерция — поставь is_ad: false.

    JSON СТРУКТУРА:
    {{
      "is_ad": true/false,
      "deal_type": "rent",
      "property_type": "apartment" | "room" | "studio" | "house" | null,
      "price_value": number | null,
      "rooms": number | null,
      "area_sqm": number | null,
      "address_raw": "string",
      "contact_phone": "string | null",
      "contact_tg": "string | null"
    }}

    Правила:
    - Телефон приводи к формату 79001234567.
    - Только JSON, без лишних слов.

    ТЕКСТ:
    {raw_text}
    """
    try:
        response = model.generate_content(prompt)
        # Очистка от markdown-обертки ```json ... ```
        clean_json = re.sub(r'```json|```', '', response.text).strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"⚠️ Ошибка ИИ: {e}")
        return None

async def main():
    print("🚀 Запуск Завода v1.0 (Smart Filter)...")
    
    async with TelegramClient(TELEGRAM_SESSION, TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
        # 1. Загружаем активные каналы и их конфиги
        res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
        
        for ch in res_ch.data:
            print(f"📡 Обработка канала: {ch['username']}")
            config = ch.get('parser_config', {})
            
            try:
                # 2. Собираем последние посты
                async for msg in client.iter_messages(ch['username'], limit=20):
                    if not msg.text: continue
                    
                    # 3. Применяем Умный фильтр и чистку
                    cleaned_text, reason = clean_text_by_config(msg.text, config)
                    
                    status = "new" if reason == "ok" else "ignored"
                    
                    # Записываем в RAW_POSTS
                    data = {
                        "channel_id": ch['id'],
                        "tg_post_id": msg.id,
                        "text": msg.text,
                        "cleaned_text": cleaned_text, # Сохраняем результат чистки
                        "status": status,
                        "ignore_reason": reason if status == "ignored" else None
                    }
                    
                    supabase.table("eraw_posts").upsert(data, on_conflict="channel_id, tg_post_id").execute()
            
            except Exception as e:
                print(f"❌ Ошибка при чтении канала {ch['username']}: {e}")
            
            await asyncio.sleep(2) # Пауза для защиты от бана ТГ

        # 4. ОЧЕРЕДЬ ОБРАБОТКИ (Прогон через ИИ)
        res_new = supabase.table("eraw_posts").select("*").eq("status", "new").limit(15).execute()
        
        for post in res_new.data:
            print(f"🧠 ИИ анализирует пост {post['id']}...")
            
            # Используем cleaned_text, если он есть, иначе оригинал
            text_to_parse = post['cleaned_text'] if post['cleaned_text'] else post['text']
            
            ai_result = await process_with_ai(text_to_parse)
            
            if ai_result:
                # Пишем в eparsed_posts
                supabase.table("eparsed_posts").insert({
                    "raw_post_id": post['id'],
                    "json_data": ai_result,
                    "is_ad": ai_result.get("is_ad", False),
                    "schema_version": 1
                }).execute()
                
                # Если это объявление — в финальную витрину
                if ai_result.get("is_ad") is True:
                    ready_data = {
                        "raw_post_id": post['id'],
                        "channel_id": post['channel_id'],
                        "deal_type": ai_result.get("deal_type"),
                        "property_type": ai_result.get("property_type"),
                        "price_value": ai_result.get("price_value"),
                        "rooms": ai_result.get("rooms"),
                        "area_sqm": ai_result.get("area_sqm"),
                        "address_raw": ai_result.get("address_raw"),
                        "contact_phone": ai_result.get("contact_phone"),
                        "contact_tg": ai_result.get("contact_tg")
                    }
                    supabase.table("eready_ads").upsert(ready_data, on_conflict="raw_post_id").execute()
                    print(f"✅ Объявление {post['id']} добавлено в витрину!")
                
                # Обновляем статус
                supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
            else:
                supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()

    print("🏁 Работа завершена.")

if __name__ == "__main__":
    asyncio.run(main())
