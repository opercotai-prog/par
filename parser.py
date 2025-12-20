import os
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetHistoryRequest
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
        # Берем 40 последних постов
        history = await client(GetHistoryRequest(
            peer=channel,
            limit=40,
            offset_date=None, offset_id=0, max_id=0, min_id=0, add_offset=0, hash=0
        ))

        if not history.messages:
            print(f"   ❌ Сообщений в канале вообще не найдено!")
            return

        found_in_channel = 0
        keywords = ["сдам", "сдаю", "аренда", "цена", "₽", "сутки", "месяц"]

        for msg in history.messages:
            if not msg.text:
                continue

            text_lower = msg.text.lower()
            
            # ПРОВЕРКА: есть ли ключевые слова?
            is_match = any(word in text_lower for word in keywords)

            # Для отладки печатаем ПЕРВУЮ строку каждого сообщения, которое видим
            first_line = msg.text.split('\n')[0][:100]
            print(f"   🔹 ID {msg.id}: {first_line} | (Match: {is_match})")

            if is_match:
                record = {
                    "platform": "telegram",
                    "source_channel": channel,
                    "external_id": str(msg.id),
                    "city": "Диагностика",
                    "raw_text": msg.text[:3000],
                    "is_published": True
                }

                try:
                    supabase.table("ads").upsert(record).execute()
                    found_in_channel += 1
                except Exception as db_err:
                    print(f"      ⚠️ Ошибка записи в БД: {db_err}")

        print(f"✅ Итог по {channel}: сохранено {found_in_channel} из 40")

    except Exception as e:
        print(f"❌ Ошибка канала {channel}: {e}")

async def main():
    print("🚀 СТАРТ ДИАГНОСТИКИ")
    await client.start()
    for channel in CHANNELS:
        await process_channel(channel)
        await asyncio.sleep(2)
    await client.disconnect()
    print("\n🏁 ПРОВЕРКА ЗАВЕРШЕНА")

if __name__ == "__main__":
    asyncio.run(main())
