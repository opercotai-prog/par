import os
import re
import asyncio
from datetime import datetime, timezone
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- НАСТРОЙКИ ИЗ GITHUB SECRETS ---
TG_API_ID = int(os.getenv("TG_API_ID"))
TG_API_HASH = os.getenv("TG_API_HASH")
TG_SESSION = os.getenv("TG_SESSION_STRING")
SUPABASE_URL = os.getenv("SUPABASEE_URL")
SUPABASE_KEY = os.getenv("SUPABASEE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def parse_post_no_ai(text):
    """
    Чистая бинарная логика и парсинг хвоста через Regex.
    """
    clean_text = text.replace('\xa0', ' ').strip()
    
    # 1. ЯДРО: ПРОВЕРКА ТЕЛЕФОНА
    # Удаляем всё кроме цифр, чтобы найти номер в любом формате
    digits_only = re.sub(r'[^\d]', '', clean_text)
    phone_match = re.search(r'(7|8)9\d{9}', digits_only)
    if not phone_match:
        return None
    phone = phone_match.group(0)

    # 2. ЯДРО: ПРОВЕРКА КЛЮЧЕЙ АРЕНДЫ
    rent_keywords = ['сдам', 'сдается', 'сдаётся', 'собственник', 'аренда', 'евродвушка', 'студия']
    if not any(word in clean_text.lower() for word in rent_keywords):
        return None

    # 3. ХВОСТ: ПОИСК ЦЕНЫ
    price = 0
    # Ищем числа от 10 до 200 (для форматов 25к, 30 т.р.) и от 5000 до 200000
    # Учитываем пробелы: "30 000"
    price_pattern = r'(\d[\d\s]{1,6})\s*(?:тыс|т\.р|тр|руб|₽|р\.|\s*\+|в месяц)'
    matches = re.finditer(price_pattern, clean_text, re.IGNORECASE)
    
    for match in matches:
        val_str = re.sub(r'\s+', '', match.group(1))
        val = int(val_str)
        
        # Если число маленькое (например 25), превращаем в 25000
        if 10 <= val <= 200:
            val = val * 1000
            
        if 5000 <= val <= 200000:
            # Проверка контекста: нет ли рядом слова "залог" или "депозит"
            start, end = match.span()
            context = clean_text[max(0, start-25):start].lower()
            if 'залог' not in context and 'депозит' not in context:
                price = val
                break

    # 4. ХВОСТ: ПОИСК АДРЕСА
    address = "Адрес не найден"
    addr_markers = ['ул.', 'улица', 'пр.', 'проспект', 'мкр', 'жк', 'адресу', 'район', 'тракт', 'подгорная']
    lines = clean_text.split('\n')
    for line in lines:
        if any(marker in line.lower() for marker in addr_markers):
            # Берем строку и чистим от лишних символов в начале
            address = re.sub(r'^[^\w\sа-яА-Я]+', '', line).strip()
            break

    return {
        "price": price,
        "address": address,
        "phone": phone
    }

async def run_task():
    client = TelegramClient(StringSession(TG_SESSION), TG_API_ID, TG_API_HASH)
    await client.start()

    # Берем активный канал из базы
    channel_id = "arendatumen72rus"
    
    # Даты: 28.01.2026 - 29.01.2026
    start_date = datetime(2026, 1, 28, tzinfo=timezone.utc)
    end_date = datetime(2026, 2, 01, tzinfo=timezone.utc)

    print(f"🚀 Запуск парсинга {channel_id} без ИИ...")

    async for msg in client.iter_messages(channel_id, limit=300):
        if msg.date < start_date: break
        if msg.date > end_date: continue
        if not msg.text or len(msg.text) < 30: continue

        # Логика парсинга
        result = parse_post_no_ai(msg.text)

        if result:
            try:
                # Вставка в Supabase
                supabase.table("posts").insert({
                    "channel_id": f"@{channel_id}",
                    "post_text": msg.text.strip(),
                    "price": result['price'],
                    "address": result['address'],
                    "phone": result['phone']
                }).execute()
                print(f"✅ Сохранено: {result['price']} руб. | {result['address']} | тел: {result['phone']}")
            except Exception as e:
                # Ошибка будет если такой пост уже есть (по желанию можно добавить constraint)
                continue

    print("🏁 Сбор завершен.")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
