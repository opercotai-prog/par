import os
import re
import hashlib
import asyncio
import json
import requests
from datetime import datetime, timezone
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# Ключи
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_str = os.getenv("TG_SESSION_STRING")
supabase_url = os.getenv("SUPABASEE_URL")
supabase_key = os.getenv("SUPABASEE_KEY")
gemini_key = os.getenv("GEMINI_KEY")

supabase = create_client(supabase_url, supabase_key)

def analyze_with_ai(text, city, config_instr):
    """Использование Gemini для извлечения ЯДРА и ХВОСТА"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    
    prompt = f"""
    Выдели данные из объявления (г. {city}). 
    ИНСТРУКЦИЯ КАНАЛА: {config_instr}
    ТЕКСТ: "{text}"
    ВЕРНИ СТРОГО JSON:
    {{
      "is_offer": bool,
      "price": int,
      "category": "studio/1-room/2-room/3-room/room",
      "address": "str",
      "phone": "str",
      "details": {{ "deposit": int, "rc": "название ЖК если есть" }}
    }}
    """
    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=20)
        if response.status_code == 200:
            raw = response.json()['candidates'][0]['content']['parts'][0]['text']
            return json.loads(re.sub(r'```json|```', '', raw).strip())
    except: return None

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    res = supabase.table("channels").select("*").eq("username", "arendatumen72rus").single().execute()
    ch = res.data
    conf = ch['parser_config']
    
    # Настройка дат
    start_date = datetime(2026, 1, 27, tzinfo=timezone.utc)
    end_date = datetime(2026, 1, 29, tzinfo=timezone.utc)

    async for msg in client.iter_messages(ch['username'], offset_date=end_date, limit=100):
        if msg.date < start_date: break
        if not msg.text or len(msg.text) < 30: continue

        # 1. Быстрый фильтр спама
        if any(m.lower() in msg.text.lower() for m in conf.get('extraction_rules', {}).get('is_spam_markers', [])):
            continue

        # 2. ИИ-АНАЛИЗ (Вместо тупого кода)
        data = analyze_with_ai(msg.text, "Тюмень", conf.get('ai_parsing_instructions'))
        
        if not data or not data.get('is_offer') or data.get('price', 0) < 5000:
            continue

        # 3. Сохранение
        content_hash = hashlib.md5(msg.text.encode()).hexdigest()
        post_id = None
        try:
            p_res = supabase.table("posts").insert({
                "channel_id": ch['id'], "telegram_msg_id": msg.id,
                "deal_type": "rent", "category": data['category'],
                "price": data['price'], "city": "Тюмень",
                "raw_text_cleaned": msg.text.split('Подпишись')[0].strip(),
                "content_hash": content_hash,
                "details": data['details']
            }).execute()
            
            if p_res.data and data.get('phone'):
                supabase.table("contacts").insert({
                    "post_id": p_res.data[0]['id'],
                    "phones": [data['phone']],
                    "links": {"url": f"https://t.me/{ch['username']}/{msg.id}"}
                }).execute()
            print(f"✅ ИИ ДОБАВИЛ: #{msg.id} | {data['price']} руб | {data['category']} | {data['address']}")
        except: continue

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
