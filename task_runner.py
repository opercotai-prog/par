import os, re, hashlib, asyncio, json, requests
from datetime import datetime, timezone
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# Ключи (используем те имена, что у тебя в GitHub Secrets)
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_str = os.getenv("TG_SESSION_STRING")
supabase_url = os.getenv("SUPABASEE_URL")
supabase_key = os.getenv("SUPABASEE_KEY")
gemini_key = os.getenv("GEMINI_KEY")

supabase = create_client(supabase_url, supabase_key)

def analyze_with_ai(text, city, config_instr):
    """Твоя рабочая функция без изменений в логике запроса"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    prompt = f"Извлеки данные (г. {city}): {text}. Инструкция: {config_instr}. Верни JSON: {{'price': int, 'address': str, 'phone': str, 'is_offer': bool}}"
    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
        if response.status_code == 200:
            raw = response.json()['candidates'][0]['content']['parts'][0]['text']
            # Чистим JSON от лишних знаков
            clean_json = re.sub(r'```json|```', '', raw).strip()
            return json.loads(clean_json)
    except Exception as e:
        print(f"Ошибка ИИ: {e}")
        return None

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    # 1. Берем данные канала из новой таблицы
    res = supabase.table("channels_passport").select("*").eq("channel_id", "@arendatumen72rus").single().execute()
    ch = res.data
    passport = ch['post_passport'] # Это наш JSON с правилами
    city = ch['city']

    # 2. Даты: 28.01.2026 - 29.01.2026
    start_date = datetime(2026, 1, 28, tzinfo=timezone.utc)
    end_date = datetime(2026, 1, 30, tzinfo=timezone.utc)

    print(f"🚀 Сбор @{ch['channel_id']} за 28-29 января...")

    async for msg in client.iter_messages(ch['channel_id'], offset_date=end_date):
        if msg.date < start_date: break
        if not msg.text or len(msg.text) < 30: continue

        # --- 1. ЯДРО (Бинарная проверка кодом) ---
        clean_text = msg.text.strip()
        has_phone = re.search(r'\+?\d{10,12}', clean_text.replace(' ', '').replace('-', ''))
        is_rent = any(word in clean_text.lower() for word in ['сдам', 'аренда', 'собственник'])

        if not (has_phone and is_rent):
            continue

        # --- 2. ХВОСТ (Анализ через ИИ по инструкции из паспорта) ---
        # Передаем в ИИ правила из post_passport['price_rule'] и т.д.
        instr = f"Цена: {passport['price_rule']}. Адрес: {passport['address_rule']}. Игнорируй: {passport['ignore_noise']}"
        
        ai_data = analyze_with_ai(clean_text, city, instr)

        if ai_data and ai_data.get('is_offer'):
            try:
                # --- 3. ЗАПИСЬ В ТАБЛИЦУ POSTS ---
                supabase.table("posts").insert({
                    "channel_id": ch['channel_id'],
                    "post_text": clean_text,
                    "price": ai_data.get('price'),
                    "address": ai_data.get('address'),
                    "phone": ai_data.get('phone')
                }).execute()
                print(f"✅ В базу: #{msg.id} | {ai_data.get('price')} руб | {ai_data.get('address')}")
            except Exception as e:
                print(f"❌ Ошибка записи: {e}")
                continue

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
