import os
import re
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetHistoryRequest
from supabase import create_client

# ==========================================
# 1. НАСТРОЙКИ
# ==========================================
API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
SESSION_STRING = os.getenv("TG_SESSION_STRING")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

CHANNELS = ["msk_flats", "arendakvartirkalingrad", "arendamsk_mo"]
CITY_DEFAULT = "Москва"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)

# ==========================================
# 2. УЛУЧШЕННЫЕ ФУНКЦИИ ПАРСИНГА
# ==========================================

def parse_price(text):
    """Супер-поиск цены: понимает 3 000, 3.000, 3'000, 30000 руб"""
    # 1. Сначала ищем кусок текста, похожий на цену: цифры с символом валюты
    # Ищем: (цифры с возможными пробелами/точками внутри) + (руб/₽)
    pattern = r'(\d[\d\s\.\,\']{2,10})\s*(₽|руб|rub|р\.)'
    match = re.search(pattern, text.lower())
    
    if match:
        price_str = match.group(1)
        # Удаляем всё, кроме цифр (пробелы, точки, запятые, апострофы)
        price_digits = re.sub(r'\D', '', price_str)
        if price_digits:
            return int(price_digits)
    return None

def parse_contact(text):
    """Ищет телефон или юзернейм"""
    phone_match = re.search(r'(?:\+7|8)[\s\(-]*\d{3}[\s\)-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}', text)
    if phone_match:
        phone = re.sub(r'\D', '', phone_match.group(0))
        if phone.startswith("8"): phone = "7" + phone[1:]
        return f"+{phone}"
    
    username_match = re.search(r'@[\w_]{3,}', text)
    if username_match:
        return username_match.group(0)
    
    return "Не указан"

# ==========================================
# 3. ОСНОВНАЯ ЛОГИКА
# ==========================================

async def process_channel(channel):
    print(f"\n📡 --- КАНАЛ: {channel} ---")
    try:
        # Увеличим лимит до 30, чтобы точно зацепить объявления
        history = await client(GetHistoryRequest(
            peer=channel,
            limit=30,
            offset_date=None, offset_id=0, max_id=0, min_id=0, add_offset=0, hash=0
        ))

        found_in_channel = 0
        for msg in history.messages:
            if not msg.text:
                continue

            # ОЧЕНЬ ВАЖНО: Выводим начало сообщения для отладки
            preview = msg.text.replace('\n', ' ')[:60]
            price = parse_price(msg.text)
            
            if price:
                contact = parse_contact(msg.text)
                print(f"   ✅ НАЙДЕНО: [ID {msg.id}] Цена: {price} | Контакт: {contact} | Текст: {preview}...")
                
                record = {
                    "platform": "telegram",
                    "source_channel": channel,
                    "external_id": str(msg.id),
                    "city": CITY_DEFAULT,
                    "price": price,
                    "contact_phone": contact,
                    "raw_text": msg.text[:2500],
                    "is_published": True
                }

                try:
                    supabase.table("ads").upsert(record).execute()
                    found_in_channel += 1
                except Exception as db_err:
                    print(f"      ⚠️ Ошибка БД: {db_err}")
            else:
                # Этот принт покажет нам, что именно мы пропустили
                # Если здесь много реальных объявлений, значит regex плохой
                pass 

        print(f"🏁 Итог по каналу: найдено {found_in_channel} объявлений.")

    except Exception as e:
        print(f"❌ Ошибка канала {channel}: {e}")

async def main():
    print("🚀 СТАРТ ПАРСЕРА")
    await client.start()
    
    for channel in CHANNELS:
        await process_channel(channel)
        await asyncio.sleep(1)

    await client.disconnect()
    print("\n✅ ВСЕ КАНАЛЫ ОБРАБОТАНЫ")

if __name__ == "__main__":
    asyncio.run(main())
