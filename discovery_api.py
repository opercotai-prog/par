import os, asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import Channel
from supabase import create_client

# Настройки из Secrets
API_ID = int(os.getenv("TG_API_ID"))
API_HASH = os.getenv("TG_API_HASH")
SESSION_STRING = os.getenv("TG_SESSION_STRING")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

tg_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

SEARCH_QUERIES = ["аренда Тюмень", "снять квартиру Тюмень", "жилье Тюмень"]

async def main():
    await tg_client.start()
    for query in SEARCH_QUERIES:
        result = await tg_client(SearchRequest(q=query, limit=50))
        for chat in result.chats:
            if isinstance(chat, Channel) and chat.username:
                data = {
                    "username": chat.username.lower(),
                    "title": chat.title,
                    "stage": "seed",
                    "source": "api_search"
                }
                supabase.table("channels").upsert(data, on_conflict="username").execute()
    await tg_client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
