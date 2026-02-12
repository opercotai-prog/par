import os
import asyncio
import json
import requests
import re
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- НАСТРОЙКИ (Берутся из GitHub Secrets) ---
API_ID = os.environ.get('TG_API_ID')
API_HASH = os.environ.get('TG_API_HASH')
SESSION_STRING = os.environ.get('TG_SESSION_STRING')
GEMINI_KEY = os.environ.get('GEMINI_KEY')
SUPABASE_URL = os.environ.get('SUPABASEE_URL') 
SUPABASE_KEY = os.environ.get('SUPABASEE_KEY')

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def simple_clean_text(text, config):
    """
    ХИРУРГИЧЕСКАЯ ОЧИСТКА:
    Отрезает только рекламный хвост (footer), чтобы не путать ИИ.
    """
    if not text or len(text) < 30:
        return None, "too_short"
    
    cleaned_text = text
    filters = config.get('filters', {}) if config else {}
    
    # Режем только футер по маркерам из БД
    for fc in filters.get('footer_cutters', []):
        idx = cleaned_text.lower().find(fc.lower())
        if idx != -1:
            cleaned_text = cleaned_text[:idx]
            
    return cleaned_text.strip(), "ok"

async def process_with_ai(text):
    """
    ИИ-ПАРСЕР С УЛУЧШЕННЫМ ПРОМПТОМ И СНЯТЫМИ ФИЛЬТРАМИ БЕЗОПАСНОСТИ
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    prompt = f"""
    Ты — профессиональный робот-парсер недвижимости. Твоя задача — извлечь данные из текста.

    ПРАВИЛА:
    1. Если в тексте человек СДАЕТ (квартиру, комнату, студию, дом) — это "is_ad": true.
    2. Если текст ОЧЕНЬ короткий (например: "Сдам 1к, 30тр, тел..."), это ВСЕ РАВНО объявление. Вытащи из него всё возможное.
    3. Если человек ИЩЕТ (пишет "сниму", "ищу") — это "is_ad": false.
    4. Если это новость, ипотека, совет или реклама услуг — это "is_ad": false.
    5. Контакты: телефон извлекай только цифрами (79001234567), юзернейм ТГ — без @.

    ВЫДАЙ СТРОГИЙ JSON:
    {{
      "is_ad": boolean,
      "deal_type": "rent",
      "property_type": "apartment" | "house" | "studio" | "room" | null,
      "price_value": number | null,
      "rooms": number | null,
      "area_sqm": number | null,
      "address_raw": "string | null",
      "contact_phone": "string | null",
      "contact_tg": "string | null"
    }}

    ТЕКСТ ОБЪЯВЛЕНИЯ:
    {text}
    """
    
    # Настройки безопасности (отключаем блокировку "подозрительного" контента)
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
    ]

    try:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "safetySettings": safety_settings
        }
        resp = requests.post(url, json=payload, timeout=25)
        res_json = resp.json()

        if 'candidates' not in res_json:
            print(f"⚠️ Ошибка Gemini (Safety/Quota): {res_json}")
            return None

        raw_ai_text = res_json['candidates'][0]['content']['parts'][0]['text']
        # Чистим JSON от возможных markdown-тегов ```json ... ```
        clean_json = re.sub(r'```json|```', '', raw_ai_text).strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"⚠️ Системная ошибка ИИ: {e}")
        return None

async def main():
    print("🚀 Запуск Завода v2.1 (Исправленный)...")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    # 1. СБОР И ПРЕДВАРИТЕЛЬНАЯ ОЧИСТКА
    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    for ch in res_ch.data:
        print(f"📡 Мониторинг: {ch['username']}")
        config = ch.get('parser_config', {})
        
        try:
            async for msg in client.iter_messages(ch['username'], limit=30):
                if not msg.text: continue
                
                # Только режем хвост, решение принимает ИИ позже
                cleaned, reason = simple_clean_text(msg.text, config)
                
                supabase.table("eraw_posts").upsert({
                    "channel_id": ch['id'],
                    "tg_post_id": msg.id,
                    "text": msg.text,
                    "cleaned_text": cleaned if cleaned else msg.text,
                    "status": "new" if cleaned else "ignored",
                    "ignore_reason": reason if not cleaned else None
                }, on_conflict="channel_id, tg_post_id").execute()
        except Exception as e:
            print(f"❌ Ошибка сбора с канала {ch['username']}: {e}")

    # 2. ОБРАБОТКА ОЧЕРЕДИ (ИИ-СУДЬЯ)
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").limit(15).execute()
    
    for post in res_new.data:
        print(f"🧐 ИИ оценивает пост {post['id']}...")
        
        # Передаем очищенный текст
        text_to_parse = post['cleaned_text'] if post['cleaned_text'] else post['text']
        ai_data = await process_with_ai(text_to_parse)
        
        if ai_data:
            # А) Сохраняем решение ИИ
            supabase.table("eparsed_posts").insert({
                "raw_post_id": post['id'],
                "is_ad": ai_data.get('is_ad', False),
                "json_data": ai_data,
                "schema_version": 1
            }).execute()

            # Б) Если ИИ подтвердил, что это аренда — в витрину
            if ai_data.get('is_ad') is True:
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
                    print(f"✅ ПРИНЯТО: {ai_data.get('price_value')} руб.")
                except Exception as e:
                    print(f"⚠️ Ошибка вставки в ready_ads: {e}")
            else:
                print(f"❌ ОТКЛОНЕНО: Не является арендой")

            # Обновляем статус на завершенный
            supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        else:
            # Если ИИ не ответил (Safety или ошибка)
            supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()
            print(f"❌ ОШИБКА: Пост {post['id']} не обработан.")

    await client.disconnect()
    print("🏁 Работа завершена.")

if __name__ == "__main__":
    asyncio.run(main())
