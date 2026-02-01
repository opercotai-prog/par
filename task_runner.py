import os, re, hashlib, asyncio, json, requests
from datetime import datetime, timezone
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# Настройки (из Environment Variables)
TG_API_ID = int(os.getenv("TG_API_ID"))
TG_API_HASH = os.getenv("TG_API_HASH")
TG_SESSION = os.getenv("TG_SESSION_STRING")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_KEY = os.getenv("GEMINI_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

async def main():
    client = TelegramClient(StringSession(TG_SESSION), TG_API_ID, TG_API_HASH)
    await client.start()

    # 1. Получаем паспорт канала из базы
    res = supabase.table("channels_passport").select("*").eq("channel_id", "@arendatumen72rus").single().execute()
    ch = res.data
    passport = ch['post_passport']

    # 2. Устанавливаем границы дат (28.01.2026 - 29.01.2026 включительно)
    # offset_date — это точка начала (сверху вниз), поэтому берем начало 30-го числа
    start_border = datetime(2026, 1, 28, 0, 0, 0, tzinfo=timezone.utc)
    end_border = datetime(2026, 1, 30, 0, 0, 0, tzinfo=timezone.utc)

    print(f"🚀 Начинаю сбор @{ch['channel_id']} за 28-29 января...")

    async for msg in client.iter_messages(ch['channel_id'], offset_date=end_border):
        # Если сообщение старше 28-го — выходим из цикла
        if msg.date < start_border:
            break
        
        # Пропускаем пустые или короткие сообщения
        if not msg.text or len(msg.text) < 20:
            continue

        # --- ШАГ 1: ЯДРО (БИНАРНО) ---
        clean_text = msg.text.strip()
        has_phone = re.search(r'\+?\d{10,12}', clean_text.replace(' ', '').replace('-', ''))
        is_rent = any(word in clean_text.lower() for word in ['сдам', 'аренда', 'собственник'])

        if not (has_phone and is_rent):
            print(f"  ⏭ Пропуск #{msg.id}: Нет ядра (телефона или ключей)")
            continue

        # --- ШАГ 2: ХВОСТ (ИИ ПО ПАСПОРТУ) ---
        print(f"  🔍 Анализ #{msg.id}...")
        
        prompt = f"""Объявление: "{clean_text}"
        Инструкция для этого канала:
        - Цена: {passport['price_rule']}
        - Адрес: {passport['address_rule']}
        - Игнорируй: {passport['ignore_noise']}
        Верни JSON: {{"price": int, "address": "str", "phone": "str", "is_offer": bool}}"""

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}"
            resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
            ai_data = json.loads(re.sub(r'```json|```', '', resp.json()['candidates'][0]['content']['parts'][0]['text']).strip())

            if ai_data.get('is_offer'):
                # Запись в базу
                supabase.table("posts").insert({
                    "channel_id": ch['channel_id'],
                    "post_text": clean_text,
                    "price": ai_data['price'],
                    "address": ai_data['address'],
                    "phone": ai_data['phone']
                }).execute()
                print(f"    ✅ СОХРАНЕНО: {ai_data['price']} руб | {ai_data['address']}")
        except Exception as e:
            print(f"    ❌ Ошибка #{msg.id}: {e}")

    await client.disconnect()
    print("🏁 Сбор завершен.")

if __name__ == "__main__":
    asyncio.run(main())
