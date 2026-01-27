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
gemini_key = os.getenv("GEMINI_KEY") # Добавь этот секрет в GitHub!

supabase = create_client(supabase_url, supabase_key)

# --- ФУНКЦИЯ ИИ (Твой Gemini REST API) ---
def analyze_with_ai(text, city_hint):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    
    prompt = f"""
    Проанализируй объявление об аренде в городе {city_hint}.
    Текст: "{text}"
    Верни ТОЛЬКО JSON:
    {{
      "price": число_или_null,
      "category": "studio/1-room/2-room/3-room/room/null",
      "address": "улица и номер дома или null",
      "is_agent": true/false,
      "comment": "почему так решил"
    }}
    """
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            answer = result['candidates'][0]['content']['parts'][0]['text']
            cleaned = re.sub(r'```json|```', '', answer).strip()
            return json.loads(cleaned)
    except Exception as e:
        print(f"      ❌ Ошибка AI: {e}")
    return None

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    # Берем активный канал
    res = supabase.table("channels").select("*").eq("username", "arendatumen72rus").single().execute()
    if not res.data: return
    
    ch = res.data
    conf = ch['parser_config']
    last_id = ch.get('last_message_id', 0)
    city = conf['typing'].get('geo_city', 'Тюмень')

    async for msg in client.iter_messages(ch['username'], min_id=last_id, reverse=True, limit=50):
        if not msg.text or len(msg.text) < 30: continue
        
        # 1. ПЕРВИЧНАЯ ОЧИСТКА (Код)
        clean_text = msg.text.split('#')[0].split('________')[0].strip()
        
        # Попытка найти цену кодом
        price_found = re.findall(r'(\d[\d\s]{3,})\s*(?:₽|руб|т\.р|тыс)', clean_text.replace('\xa0', ' '))
        price = int(re.sub(r'\s+', '', price_found[0])) if price_found else 0
        
        category = "other"
        ai_analysis = "Processed by Regex"

        # 2. ЕСЛИ КОД НЕ СПРАВИЛСЯ — ВКЛЮЧАЕМ ИИ (Красный коридор)
        if price == 0:
            print(f"🔍 Пост {msg.id}: Код не нашел цену. Запрос к Gemini...")
            ai_data = analyze_with_ai(clean_text, city)
            if ai_data:
                price = ai_data.get('price') or 0
                category = ai_data.get('category') or "other"
                ai_analysis = ai_data.get('comment', "AI successful")
                # Можно также обновить адрес в деталях
            else:
                print(f"⏩ Пропуск {msg.id}: ИИ тоже не помог.")
                continue

        # Если даже после ИИ цена 0 — это не объявление (реклама услуг и т.д.)
        if price < 5000: 
            continue

        # 3. СОХРАНЕНИЕ
        content_hash = hashlib.md5(clean_text.encode()).hexdigest()
        post_data = {
            "channel_id": ch['id'],
            "telegram_msg_id": msg.id,
            "deal_type": "rent",
            "category": category,
            "price": price,
            "city": city,
            "raw_text_cleaned": clean_text,
            "content_hash": content_hash,
            "details": {"ai_comment": ai_analysis, "full_text": msg.text}
        }

        try:
            ins_res = supabase.table("posts").insert(post_data).execute()
            if ins_res.data:
                # Шаг 3: Контакты (можно тоже через AI или Regex)
                phones = re.findall(r'\+?\d{10,12}', clean_text)
                supabase.table("contacts").insert({
                    "post_id": ins_res.data[0]['id'],
                    "phones": phones
                }).execute()
                print(f"✅ Добавлен: #{msg.id} | Цена: {price} | Тип: {category}")
        except Exception as e:
            print(f"❌ Ошибка записи {msg.id}: {e}")

        last_id = msg.id

    # Обновляем ID последнего сообщения
    supabase.table("channels").update({"last_message_id": last_id}).eq("id", ch['id']).execute()
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
