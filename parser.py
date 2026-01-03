import os
import asyncio
from datetime import datetime, timezone

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Channel

from supabase import create_client

# ==========================================================
# 1. НАСТРОЙКИ (МЕНЯЕШЬ ТОЛЬКО ЭТО)
# ==========================================================

# Город / регион
CITY = "Тюмень"

# Поисковые темы (можно менять / расширять)
SEARCH_QUERIES = [
    "аренда квартир Тюмень",
    "сдам квартиру Тюмень",
    "сниму квартиру Тюмень",
    "аренда жилья Тюмень",
    "недвижимость аренда Тюмень",
    "rent apartment Темень",
]

# Сколько результатов брать на каждый запрос
SEARCH_LIMIT = 50

# Источник (для аналитики)
SOURCE = "auto_search"

# ==========================================================
# 2. ENV
# ==========================================================

API_ID = int(os.getenv("TG_API_ID"))
API_HASH = os.getenv("TG_API_HASH")
SESSION_STRING = os.getenv("TG_SESSION_STRING")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# ==========================================================
# 3. CLIENTS
# ==========================================================

tg_client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH
)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================================
# 4. ОБРАБОТКА КАНАЛА
# ==========================================================

async def save_channel(channel: Channel):
    """
    Забираем метаданные канала и сохраняем в Supabase
    """
    try:
        full = await tg_client(GetFullChannelRequest(channel))

        record = {
            "username": channel.username,
            "title": channel.title,
            "description": full.full_chat.about,
            "participants_count": full.full_chat.participants_count,
            "city": CITY,
            "stage": "discovered",   # найден автоматически
            "source": SOURCE,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        supabase.table("channels").upsert(
            record,
            on_conflict="username"
        ).execute()

        print(f"✅ saved | {channel.username} | members: {record['participants_count']}")

    except Exception as e:
        print(f"⚠️ ошибка сохранения {channel.username}: {e}")

# ==========================================================
# 5. ПОИСК КАНАЛОВ ПО ТЕМЕ
# ==========================================================

async def search_channels(query: str):
    """
    Поиск каналов в Telegram по текстовому запросу
    """
    print(f"\n🔎 Поиск: '{query}'")

    result = await tg_client(
        SearchRequest(
            q=query,
            limit=SEARCH_LIMIT
        )
    )

    for chat in result.chats:
        # Нас интересуют ТОЛЬКО каналы с username
        if isinstance(chat, Channel) and chat.username:
            await save_channel(chat)
            await asyncio.sleep(0.8)  # анти-флуд

# ==========================================================
# 6. MAIN
# ==========================================================

async def main():
    print("🚀 START AUTO CHANNEL DISCOVERY")
    print(f"🏙 Город: {CITY}")

    await tg_client.start()

    for query in SEARCH_QUERIES:
        await search_channels(query)
        await asyncio.sleep(2)

    await tg_client.disconnect()
    print("\n🏁 DONE")

if __name__ == "__main__":
    asyncio.run(main())
