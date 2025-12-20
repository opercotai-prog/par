import os
import re
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetHistoryRequest
from supabase import create_client

# ==========================================
# 1. НАСТРОЙКИ И КЛЮЧИ
# ==========================================
# Эти переменные берутся из Secrets вашего репозитория GitHub
API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
SESSION_STRING = os.getenv("TG_SESSION_STRING")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Список каналов для мониторинга
CHANNELS = ["msk_flats", "arendakvartirkalingrad", "arendamsk_mo"]
CITY_DEFAULT = "Москва"

# Проверка, что все ключи на месте
if not all([API_ID, API_HASH, SESSION_STRING, SUPABASE_URL, SUPABASE_KEY]):
    print("❌ ОШИБКА: Не все Secrets добавлены в настройки GitHub!")
    exit(1)

# Инициализация клиентов
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)

# ==========================================
# 2. ФУНКЦИИ ОЧИСТКИ И ПАРСИНГА
# ==========================================

def clean_text_for_price(text):
    """Удаляет разделители в числах типа 3.000 или 3'000"""
    # Удаляем точки, запятые и апострофы, если они стоят между цифрами
    text = re.sub(r'(?<=\d)[.,\'](?=\d)', '', text)
    return text

def parse_price(text):
    """Ищет цену в тексте"""
    text_cleaned = clean_text_for_price(text)
    # Ищем число от 3 до 7 знаков, рядом с которым есть знак рубля или текст руб
    # Примеры: 3000руб, 50000 ₽, 3500 rub
    match = re.search(r'(\d{3,7})\s*(₽|руб|rub|р\.)', text_cleaned.lower())
    if match:
        return int(match.group(1))
    return None

def parse_contact(text):
    """Ищет номер телефона или @username"""
    # 1. Ищем телефон (РФ)
    phone_match = re.search(r'(?:\+7|8)[\s\(-]*\d{3}[\s\)-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}', text)
    if phone_match:
        phone = re.sub(r'\D', '', phone_match.group(0))
        if phone.startswith("8"): phone = "7" + phone[1:]
        return f"+{phone}"
    
    # 2. Ищем Telegram username (@name)
    username_match = re.search(r'@[\w_]{3,}', text)
    if username_match:
        return username_match.group(0)
    
    return "Не указан"

def parse_rooms(text):
    """Определяет количество комнат"""
    t = text.lower()
    if "студия" in t or "#студия" in t:
        return "studio"
    match = re.search(r'([1-5])\s*[-]?\s*(комн|к)\b', t)
    return match.group(1) if match else "1"

# ==========================================
# 3. ОСНОВНАЯ ЛОГИКА
# ==========================================

async def process_channel(channel):
    print(f"\n📡 Чтение канала: {channel}")
    try:
        # Получаем последние 20 сообщений из канала
        history = await client(GetHistoryRequest(
            peer=channel,
            limit=20,
            offset_date=None, offset_id=0, max_id=0, min_id=0, add_offset=0, hash=0
        ))

        found_count = 0
        for msg in history.messages:
            if not msg.text or len(msg.text) < 10:
                continue

            price = parse_price(msg.text)
            
            # Если цена найдена — обрабатываем пост
            if price:
                contact = parse_contact(msg.text)
                rooms = parse_rooms(msg.text)
                
                # Формируем запись для базы данных
                record = {
                    "platform": "telegram",
                    "source_channel": channel,
                    "external_id": str(msg.id),
                    "city": CITY_DEFAULT,
                    "price": price,
                    "rooms": rooms,
                    "contact_phone": contact,
                    "raw_text": msg.text[:2500], # Ограничение длины текста
                    "is_published": True
                }

                # Отправка в Supabase (upsert по external_id предотвращает дубликаты)
                try:
                    supabase.table("ads").upsert(record).execute()
                    print(f"   ✅ [ID {msg.id}] Сохранено: {price} руб., Контакт: {contact}")
                    found_count += 1
                except Exception as db_err:
                    print(f"   ⚠️ Ошибка БД на посте {msg.id}: {db_err}")
            
        if found_count == 0:
            print("   ℹ️ Новых подходящих объявлений не найдено.")

    except Exception as e:
        print(f"   ❌ Ошибка при работе с каналом {channel}: {e}")

async def main():
    print("🚀 Скрипт запущен")
    
    # Подключение клиента (автоматически по строке сессии)
    await client.start()
    
    # Проверка авторизации
    if not await client.is_user_authorized():
        print("❌ ОШИБКА: Сессия недействительна. Получите новую TG_SESSION_STRING!")
        return

    # Обработка всех каналов
    for channel in CHANNELS:
        await process_channel(channel)
        await asyncio.sleep(2) # Пауза между каналами, чтобы избежать флуд-фильтра

    await client.disconnect()
    print("\n🏁 Работа завершена!")

if __name__ == "__main__":
    asyncio.run(main())
