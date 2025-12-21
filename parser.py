import os
import re
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# ==========================================
# 1. НАСТРОЙКИ
# ==========================================
API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
SESSION_STRING = os.getenv("TG_SESSION_STRING")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Маппинг каналов и городов по умолчанию
CHANNELS_CONF = {
    "msk_flats": "Москва",
    "arendakvartirkalingrad": "Калининград",
    "arendamsk_mo": "Московская область"
}

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)

# ==========================================
# 2. УМНЫЕ ПАРСЕРЫ
# ==========================================

def extract_price(text):
    """Находит цену даже в форматах 5'000, 3.000, 70.000"""
    # Убираем мусор внутри цифр: 5'000 -> 5000
    cleaned_text = re.sub(r'(?<=\d)[.\', ](?=\d{3})', '', text)
    # Ищем число + валюта
    match = re.search(r'(\d{3,7})\s*(₽|руб|rub|р\.)', cleaned_text.lower())
    return int(match.group(1)) if match else None

def extract_phone(text):
    """Ищет телефон или @username"""
    # Телефон
    phone = re.search(r'(?:\+7|8)[\s\(-]*\d{3}[\s\)-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}', text)
    if phone:
        clean_phone = re.sub(r'\D', '', phone.group(0))
        if clean_phone.startswith("8"): clean_phone = "7" + clean_phone[1:]
        return f"+{clean_phone}"
    # Юзернейм
    user = re.search(r'@[\w_]{3,}', text)
    return user.group(0) if user else None

def extract_rooms(text):
    """Определяет количество комнат по тегам и ключевым словам"""
    t = text.lower()
    if "студия" in t or "studio" in t: return "studio"
    if "однокомн" in t or "1-к" in t or "1к" in t or "трёшка" not in t and "1" in t: return "1"
    if "двухкомн" in t or "2-к" in t or "2к" in t: return "2"
    if "трехкомн" in t or "3-к" in t or "трёшка" in t: return "3"
    return None

def is_ad(text):
    """Отсеивает рекламу"""
    blacklist = ["#реклама", "пицца", "стоматология", "зубы", "скидка на всё меню"]
    return any(word in text.lower() for word in blacklist)

# ==========================================
# 3. ОСНОВНАЯ ЛОГИКА
# ==========================================

async def process_channel(channel, default_city):
    print(f"📡 Обработка {channel}...")
    try:
        messages = await client.get_messages(channel, limit=30)
        
        for msg in messages:
            if not msg.text or is_ad(msg.text):
                continue

            price = extract_price(msg.text)
            
            # Сохраняем только если есть цена (признак аренды)
            if price:
                contact = extract_phone(msg.text)
                rooms = extract_rooms(msg.text)
                
                # Попытка уточнить город из текста
                city = default_city
                if "светлогорск" in msg.text.lower(): city = "Светлогорск"
                if "зеленоградск" in msg.text.lower(): city = "Зеленоградск"

                record = {
                    "platform": "telegram",
                    "source_channel": channel,
                    "external_id": str(msg.id),
                    "city": city,
                    "rooms": rooms,
                    "price": price,
                    "contact_phone": contact,
                    "raw_text": msg.text[:3000],
                    "is_published": True
                }

                try:
                    supabase.table("ads").upsert(record).execute()
                    print(f"   ✅ [ID {msg.id}] {price} руб. | {rooms}к | {contact}")
                except Exception as e:
                    if "duplicate" not in str(e):
                        print(f"   ⚠️ Ошибка БД: {e}")

    except Exception as e:
        print(f"❌ Ошибка в канале {channel}: {e}")

async def main():
    print("🚀 ПАРСЕР ЗАПУЩЕН")
    await client.start()
    
    for channel, city in CHANNELS_CONF.items():
        await process_channel(channel, city)
        await asyncio.sleep(2)

    await client.disconnect()
    print("🏁 ВСЕ ГОТОВО")

if __name__ == "__main__":
    asyncio.run(main())
