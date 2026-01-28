import os
import re
import hashlib
import asyncio
import json
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- НАСТРОЙКИ И КЛЮЧИ ---
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_str = os.getenv("TG_SESSION_STRING")
supabase_url = os.getenv("SUPABASEE_URL")
supabase_key = os.getenv("SUPABASEE_KEY")
gemini_key = os.getenv("GEMINI_KEY")

supabase = create_client(supabase_url, supabase_key)

def analyze_with_ai(text, city_hint):
  f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    prompt = f"""Проанализируй объявление об аренде в городе {city_hint}. Текст: "{text}"
    Верни ТОЛЬКО JSON: {{"price": число_или_null, "category": "studio/1-room/2-room/3-room/room/null", "address": "строка_или_null", "comment": "пояснение"}}"""
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            result = response.json()
            answer = result['candidates'][0]['content']['parts'][0]['text']
            cleaned = re.sub(r'```json|```', '', answer).strip()
            return json.loads(cleaned)
    except Exception as e:
        print(f"      ⚠️ Ошибка ИИ: {e}")
    return None

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    res = supabase.table("channels").select("*").eq("username", "arendatumen72rus").single().execute()
    if not res.data: return
    
    ch = res.data
    conf = ch['parser_config']
    last_id = ch.get('last_message_id', 0)
    city = conf['typing'].get('geo_city', 'Тюмень')

    async for msg in client.iter_messages(ch['username'], min_id=last_id, reverse=True, limit=50):
        if not msg.text or len(msg.text) < 30: continue
        
        # --- ИНИЦИАЛИЗАЦИЯ ---
        ai_analysis = "Processed by Regex"
        category = "other"
        price = 0
        
        # --- НОВЫЙ БЛОК: ОЧИСТКА ХВОСТА ---
        trash_markers = ['#', '________', 'Подписывайтесь', 'Подпишись', 'Связь с Админом', 'Наш Чат', '⚡️']
        clean_text = msg.text
        for marker in trash_markers:
            clean_text = clean_text.split(marker)[0]
        clean_text = clean_text.strip()
        
        # --- НОВЫЙ БЛОК: ПОИСК КАТЕГОРИИ (С границами слов \b) ---
        cat_patterns = {
            "1-room": [r'\b1к\b', r'1 комнатная', r'однокомнатная'],
            "2-room": [r'\b2к\b', r'2 комнатная', r'двухкомнатная'],
            "3-room": [r'\b3к\b', r'3 комнатная', r'трехкомнатная'],
            "studio": [r'студия', r'квартира-студия'],
            "room": [r'\bкомната\b', r'вобщежитии']
        }
        for cat_name, patterns in cat_patterns.items():
            for pattern in patterns:
                if re.search(pattern, clean_text, re.IGNORECASE):
                    category = cat_name
                    break
            if category != "other": break

        # --- ПОИСК ЦЕНЫ КОДОМ ---
        price_found = re.findall(r'(\d[\d\s]{3,})\s*(?:₽|руб|т\.р|тыс)', clean_text.replace('\xa0', ' '))
        if price_found:
            price = int(re.sub(r'\s+', '', price_found[0]))

        # --- ТРИГГЕР ИИ ---
        if price < 5000 or category == "other":
            print(f"🔍 Пост {msg.id}: Нужна помощь ИИ (Цена: {price}, Кат: {category})")
            ai_data = analyze_with_ai(clean_text, city)
            if ai_data:
                print(f"      🤖 Ответ ИИ: {ai_data}")
                price = ai_data.get('price') or price
                category = ai_data.get('category') or category
                ai_analysis = f"AI Success: {ai_data.get('comment', '')}"

        if price < 5000:
            last_id = msg.id
            continue

        content_hash = hashlib.md5(clean_text.encode()).hexdigest()
        post_data = {
            "channel_id": ch['id'], "telegram_msg_id": msg.id, "deal_type": "rent",
            "category": category, "price": price, "city": city,
            "raw_text_cleaned": clean_text, "content_hash": content_hash,
            "details": {"ai_comment": ai_analysis, "full_text_raw": msg.text[:500]}
        }

        try:
            ins_res = supabase.table("posts").insert(post_data).execute()
            if ins_res.data:
                phones = re.findall(r'\+?\d{10,12}', clean_text)
                supabase.table("contacts").insert({
                    "post_id": ins_res.data[0]['id'],
                    "phones": phones,
                    "links": {"msg_url": f"https://t.me/{ch['username']}/{msg.id}"}
                }).execute()
                print(f"✅ Добавлен: #{msg.id} | {price} руб | {category}")
        except Exception as e:
            if "duplicate key" not in str(e): print(f"❌ Ошибка записи #{msg.id}: {e}")

        last_id = msg.id

    supabase.table("channels").update({"last_message_id": last_id}).eq("id", ch['id']).execute()
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
