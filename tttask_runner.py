import os
import asyncio
import json
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- КЛЮЧИ ---
API_ID = os.environ.get('TG_API_ID')
API_HASH = os.environ.get('TG_API_HASH')
SESSION_STRING = os.environ.get('TG_SESSION_STRING')
GEMINI_KEY = os.environ.get('GEMINI_KEY')
SUPABASE_URL = os.environ.get('SUPABASEE_URL') 
SUPABASE_KEY = os.environ.get('SUPABASEE_KEY')

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

async def process_with_ai(text):
    """Золотой стандарт промпта"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    # Промпт настроен под твои колонки: price_value, area_sqm, property_type, address_raw
    prompt = f"""
    Верни JSON строго по схеме. Если данных нет - null.
    {{
      "is_ad": boolean,
      "deal_type": "rent" | "sale",
      "property_type": "apartment" | "house" | "studio" | "room",
      "price_value": number,
      "rooms": number,
      "area_sqm": number,
      "address_raw": "string"
    }}
    Текст: {text}
    """
    
    try:
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(url, json=payload, timeout=20)
        res_json = resp.json()
        raw_text = res_json['candidates'][0]['content']['parts'][0]['text']
        clean_json = raw_text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except:
        return None

async def main():
    print("🚀 Запуск Завода...")
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    # 1. СОБИРАЕМ СЫРЬЕ
    res_ch = supabase.table("echannels").select("id, username").eq("status", "active").execute()
    for ch in res_ch.data:
        async for msg in client.iter_messages(ch['username'], limit=15):
            if not msg.text: continue
            try:
                # Используем upsert чтобы не дублировать посты в eraw_posts
                supabase.table("eraw_posts").upsert({
                    "channel_id": ch['id'],
                    "tg_post_id": msg.id,
                    "text": msg.text,
                    "status": "new"
                }, on_conflict="channel_id, tg_post_id").execute()
            except: pass

    # 2. ОБРАБАТЫВАЕМ ОЧЕРЕДЬ (10 за раз)
    res_new = supabase.table("eraw_posts").select("*").eq("status", "new").limit(10).execute()
    for post in res_new.data:
        # Ставим статус в работе
        supabase.table("eraw_posts").update({"status": "processing"}).eq("id", post['id']).execute()
        
        ai_data = await process_with_ai(post['text'])
        
        if ai_data:
            # А) В eparsed_posts
            supabase.table("eparsed_posts").insert({
                "raw_post_id": post['id'],
                "is_ad": ai_data.get('is_ad', False),
                "payload": ai_data
            }).execute()

            # Б) В eready_ads (если это объявление)
            if ai_data.get('is_ad'):
                try:
                    supabase.table("eready_ads").insert({
                        "raw_post_id": post['id'],
                        "deal_type": ai_data.get('deal_type'),
                        "property_type": ai_data.get('property_type'),
                        "price_value": ai_data.get('price_value'),
                        "rooms": ai_data.get('rooms'),
                        "area_sqm": ai_data.get('area_sqm'),
                        "address_raw": ai_data.get('address_raw')
                    }).execute()
                    print(f"✅ Объявление #{post['id']} готово!")
                except Exception as e:
                    print(f"⚠️ Ошибка вставки в ready: {e}")

            supabase.table("eraw_posts").update({"status": "parsed"}).eq("id", post['id']).execute()
        else:
            supabase.table("eraw_posts").update({"status": "error"}).eq("id", post['id']).execute()

    await client.disconnect()
    print("🏁 Работа завершена")

if __name__ == "__main__":
    asyncio.run(main())
