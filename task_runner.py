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
    """Вызывается только для сложных постов"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    prompt = f"Извлеки данные (г. {city}): {text}. Инструкция: {config_instr}. Верни JSON: {{'price': int, 'category': str, 'address': str, 'phone': str, 'is_offer': bool}}"
    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
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
    
    # ТЕСТ за 27-28 января
    start_date = datetime(2026, 1, 27, tzinfo=timezone.utc)
    end_date = datetime(2026, 1, 29, tzinfo=timezone.utc)

    async for msg in client.iter_messages(ch['username'], offset_date=end_date, limit=100):
        if msg.date < start_date: break
        if not msg.text or len(msg.text) < 30: continue

        # --- 1. ОЧИСТКА ХВОСТА (Код) ---
        clean_text = msg.text.split('Подпишись')[0].split('⚡️')[0].split('________')[0].strip()
        
        # --- 2. ПОПЫТКА ОБРАБОТКИ КОДОМ (Regex) ---
        # Ищем цену только если рядом есть символы валюты (чтобы не путать с телефоном)
        price_found = re.findall(r'(\d[\d\s]{3,})\s*(?:₽|руб|т\.р|тыс)', clean_text.replace('\xa0', ' '))
        price = int(re.sub(r'\s+', '', price_found[0])) if price_found else 0
        
        category = "other"
        cat_map = {
            "1-room": [r'\b1к\b', r'1-к', r'однокомнатная', r'1 комнатная'],
            "2-room": [r'\b2к\b', r'2-к', r'двухкомнатная', r'2 комнатная'],
            "studio": [r'студия', r'квартира-студия']
        }
        for cat_name, patterns in cat_map.items():
            if any(re.search(p, clean_text, re.IGNORECASE) for p in patterns):
                category = cat_name
                break

        # --- 3. ВКЛЮЧАЕМ ИИ, ЕСЛИ КОД НЕ СПРАВИЛСЯ ---
        method = "regex"
        if price == 0 or category == "other":
            print(f"🔍 Пост {msg.id}: Код не справился. Зовем ИИ...")
            ai_data = analyze_with_ai(clean_text, "Тюмень", conf.get('ai_parsing_instructions'))
            if ai_data and ai_data.get('is_offer'):
                price = ai_data.get('price') or price
                category = ai_data.get('category') or category
                method = "ai_assisted"
            elif price == 0: # Если ИИ тоже не нашел цену - в мусор
                continue

        # --- 4. ЗАПИСЬ ---
        content_hash = hashlib.md5(clean_text.encode()).hexdigest()
        try:
            p_res = supabase.table("posts").insert({
                "channel_id": ch['id'], "telegram_msg_id": msg.id,
                "deal_type": "rent", "category": category, "price": price, "city": "Тюмень",
                "raw_text_cleaned": clean_text, "content_hash": content_hash,
                "details": {"method": method}
            }).execute()
            
            if p_res.data:
                # Ищем телефон (просто все цифры)
                phones = re.findall(r'\+?\d{10,12}', clean_text.replace(' ', '').replace('-', ''))
                if phones:
                    supabase.table("contacts").insert({
                        "post_id": p_res.data[0]['id'], "phones": [phones[0]],
                        "links": {"url": f"https://t.me/{ch['username']}/{msg.id}"}
                    }).execute()
            print(f"✅ Готово: #{msg.id} | {price} руб | {category} | ({method})")
        except: continue

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
