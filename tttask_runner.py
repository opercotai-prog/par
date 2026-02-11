import os
import asyncio
import json
import requests
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

def simple_clean_text(text, config):
    """
    100% УВЕРЕННЫЙ ФИЛЬТР:
    Только режем рекламный хвост. Больше ничего не трогаем.
    """
    if not text or len(text) < 40:
        return None, "too_short"
    
    cleaned_text = text
    filters = config.get('filters', {}) if config else {}
    
    # Режем только футер, если он есть в конфиге
    for fc in filters.get('footer_cutters', []):
        idx = cleaned_text.lower().find(fc.lower())
        if idx != -1:
            cleaned_text = cleaned_text[:idx]
            
    return cleaned_text.strip(), "ok"

async def process_with_ai(text):
    """ИИ — ГЛАВНЫЙ ФИЛЬТР И ПАРСЕР"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    # Максимально жесткий промпт на фильтрацию
    prompt = f"""
    Проанализируй текст объявления. Твоя задача — строго отделить аренду жилья от всего остального.

    УСТАНОВИ "is_ad": false, ЕСЛИ:
    - Человек ИЩЕТ квартиру (пишет "сниму", "ищу", "ищем").
    - Это НОВОСТЬ, совет, ипотека или юридическая инфо.
    - Это ПРОДАЖА (куплю/продам).
    - Это КОММЕРЦИЯ (офис, склад, салон).
    - Это УСЛУГИ (грузоперевозки, ремонт).

    УСТАНОВИ "is_ad": true, ТОЛЬКО ЕСЛИ:
    - Это предложение СДАТЬ в аренду квартиру, комнату, дом или студию.

    ВЫДАЙ СТРОГИЙ JSON:
    {{
      "is_ad": boolean,
      "deal_type": "rent",
      "property_type": "apartment" | "house" | "studio" | "room" | null,
      "price_value": number | null,
      "rooms": number | null,
      "area_sqm": number | null,
      "address_raw": "string | null",
      "contact_phone": "только цифры 79...",
      "contact_tg": "username без @"
    }}

    ТЕКСТ:
    {text}
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
    print("🚀 Завод v2.0: Доверие к ИИ...")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    # 1. СБОР (БЕЗ ФИЛЬТРАЦИИ)
    res_ch = supabase.table("echannels").select("*").eq("status", "active").execute()
    for ch in res_ch.data:
        config = ch.get('parser_config', {})
        async for msg in client.iter_messages(ch['username'], limit=30):
            if not msg.text: continue
            
            # Только чистим от рекламы, не удаляем посты!
            cleaned, reason = simple_clean_text(msg.text, config)
            
            supabase.table("eraw_posts").upsert({
                "channel_id": ch['id'],
                "tg_post_id": msg.id,
                "text": msg.text,
                "cleaned_text": cleaned if cleaned else msg.text,
                "status": "new" if cleaned else "ignored",
                "ignore_reason": reason if not cleaned else None
            }, on_conflict="channel_id, tg_post_id").execute()

    # 2. ОБРАБОТКА (ИИ РЕШАЕТ ВСЁ)
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").limit(15).execute()
    for post in res_new.data:
        print(f"🧐 ИИ оценивает: {post['id']}...")
        ai_data = await process_with_ai(post['cleaned_text'])
        
        if ai_data:
            # А) Сохраняем решение ИИ
            supabase.table("eparsed_posts").insert({
                "raw_post_id": post['id'],
                "is_ad": ai_data.get('is_ad', False),
                "json_data": ai_data,
                "schema_version": 1
            }).execute()

            # Б) Если ИИ сказал "ДА" — на витрину
            if ai_data.get('is_ad') is True:
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
            else:
                print(f"❌ ОТКЛОНЕНО: Не является арендой")

            supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        else:
            supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()

    await client.disconnect()
    print("🏁 Работа завершена.")

if __name__ == "__main__":
    asyncio.run(main())
