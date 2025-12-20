import os
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- Инициализация ---
API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
SESSION_STRING = os.getenv("TG_SESSION_STRING")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

CHANNELS = ["msk_flats", "arendakvartirkalingrad", "arendamsk_mo"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)

async def process_channel(channel):
    print(f"\n--- 📡 ПРОВЕРКА КАНАЛА: {channel} ---")
    try:
        # Используем более надежный метод get_messages
        messages = await client.get_messages(channel, limit=20)

        if not messages:
            print(f"   ❌ Сообщений не получено вообще.")
            return

        found_in_channel = 0
        
        for msg in messages:
            # Печатаем тип каждого сообщения для диагностики
            msg_type = type(msg).__name__
            
            # Проверяем текст или описание под фото (caption)
            text = msg.text or msg.message or ""
            
            # Печатаем абсолютно всё, что видим, чтобы понять причину пропуска
            print(f"   🔹 ID {msg.id} | Тип: {msg_type} | Текст: {text[:50].replace(chr(10), ' ')}...")

            if not text:
                continue

            # Простейший фильтр
            keywords = ["сдам", "сдаю", "аренда", "цена", "₽", "сутки", "месяц", "кв", "квартира"]
            is_match = any(word in text.lower() for word in keywords)

            if is_match:
                record = {
                    "platform": "telegram",
                    "source_channel": channel,
                    "external_id": str(msg.id),
                    "city": "Debug_City",
                    "raw_text": text[:3000],
                    "is_published": True
                }

                try:
                    supabase.table("ads").upsert(record).execute()
                    found_in_channel += 1
                except Exception as db_err:
                    print(f"      ⚠️ Ошибка БД: {db_err}")

        print(f"✅ Итог по {channel}: сохранено {found_in_channel}")

    except Exception as e:
        print(f"❌ Системная ошибка канала {channel}: {e}")

async def main():
    print("🚀 ЗАПУСК ДИАГНОСТИКИ v2")
    await client.start()
    
    # Проверка: видит ли нас телеграм вообще?
    me = await client.get_me()
    print(f"👤 Выполнен вход как: {me.first_name} (@{me.username})")

    for channel in CHANNELS:
        await process_channel(channel)
        await asyncio.sleep(2)

    await client.disconnect()
    print("\n🏁 ВСЕ ПРОВЕРКИ ЗАВЕРШЕНЫ")

if __name__ == "__main__":
    asyncio.run(main())
