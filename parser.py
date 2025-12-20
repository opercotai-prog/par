import os
import re
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetHistoryRequest
from supabase import create_client

# ==========================================
# 1. ЗАГРУЗКА НАСТРОЕК (ИЗ GITHUB SECRETS)
# ==========================================
API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
# Эта переменная решает проблему с ошибкой EOFError
SESSION_STRING = os.getenv("TG_SESSION_STRING")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Каналы для парсинга (можешь менять список)
CHANNELS = ["msk_flats", "arendakvartirkalingrad"]
CITY = "Москва"

# ==========================================
# 2. ПРОВЕРКА НАЛИЧИЯ ВСЕХ КЛЮЧЕЙ
# ==========================================
if not all([API_ID, API_HASH, SESSION_STRING, SUPABASE_URL, SUPABASE_KEY]):
    print("❌ ОШИБКА: Не все секреты (Secrets) добавлены в GitHub!")
    print("Проверь: TG_API_ID, TG_API_HASH, TG_SESSION_STRING, SUPABASE_URL, SUPABASE_KEY")
    exit(1)

# Инициализация клиентов
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)

# ==========================================
# 3. ФУНКЦИИ ПОИСКА ДАННЫХ (РЕГУЛЯРКИ)
# ==========================================
def parse_price(text):
    text = text.replace(" ", "").replace("\xa0", "") # Убираем пробелы
    m = re.search(r'(\d{4,7})\s*(₽|руб|rub)', text.lower())
    return int(m.group(1)) if m else None

def parse_rooms(text):
    t = text.lower()
    if "студ" in t: return "studio"
    m = re.search(r'([1-5])\s*[-]?\s*(комн|к)\b', t)
    return m.group(1) if m else None

def parse_phone(text):
    m = re.search(r'(?:\+7|8)[\s\(-]*\d{3}[\s\)-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}', text)
    if m:
        phone = re.sub(r'\D', '', m.group(0))
        if phone.startswith("8"): phone = "7" + phone[1:]
        return phone
    return None

# ==========================================
# 4. ЛОГИКА ПАРСИНГА КАНАЛА
# ==========================================
async def parse_channel(channel_username):
    print(f"📡 Парсим канал: {channel_username}...")
    try:
        # Получаем последние 20 сообщений
        history = await client(GetHistoryRequest(
            peer=channel_username,
            limit=20,
            offset_date=None, offset_id=0, max_id=0, min_id=0, add_offset=0, hash=0
        ))

        for msg in history.messages:
            if not msg.text: continue

            price = parse_price(msg.text)
            phone = parse_phone(msg.text)
            
            # Сохраняем, только если нашли хотя бы цену или телефон
            if price or phone:
                record = {
                    "platform": "telegram",
                    "source_channel": channel_username,
                    "external_id": str(msg.id),
                    "city": CITY,
                    "rooms": parse_rooms(msg.text),
                    "price": price,
                    "contact_phone": phone,
                    "raw_text": msg.text[:2000],
                    "is_published": True
                }
                
                # Отправка в Supabase (с защитой от дублей по external_id, если настроено в БД)
                try:
                    supabase.table("ads").upsert(record).execute()
                except Exception as e:
                    print(f"⚠️ Ошибка базы: {e}")

        print(f"✅ Канал {channel_username} обработан.")
    except Exception as e:
        print(f"❌ Ошибка при парсинге {channel_username}: {e}")

# ==========================================
# 5. ЗАПУСК
# ==========================================
async def main():
    print("🚀 Скрипт запущен...")
    await client.start() # Вход будет автоматическим по SESSION_STRING
    
    for channel in CHANNELS:
        await parse_channel(channel)
        await asyncio.sleep(1) # Пауза для защиты от спам-фильтра

    await client.disconnect()
    print("🏁 Работа завершена!")

if __name__ == "__main__":
    asyncio.run(main())
