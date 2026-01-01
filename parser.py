import os
import asyncio
import re
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest

from supabase import create_client

# =========================
# ENV VARIABLES
# =========================
TG_API_ID = int(os.environ["TG_API_ID"])
TG_API_HASH = os.environ["TG_API_HASH"]
TG_SESSION_STRING = os.environ["TG_SESSION_STRING"]

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

# =========================
# CONSTANTS
# =========================
CITY_KEYWORDS = ["тюмень", "tyumen"]
RENT_KEYWORDS = ["аренда", "сдам", "квартира", "посуточно", "жилье"]

MAX_MESSAGES_TO_SCAN = 50

# =========================
# INIT CLIENTS
# =========================
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

tg_client = TelegramClient(
    StringSession(TG_SESSION_STRING),
    TG_API_ID,
    TG_API_HASH
)

# =========================
# UTILS
# =========================
def text_contains_keywords(text: str, keywords: list[str]) -> bool:
    text = text.lower()
    return any(k in text for k in keywords)

# =========================
# MAIN LOGIC
# =========================
async def process_channel(channel_username: str):
    try:
        entity = await tg_client.get_entity(channel_username)
        full = await tg_client(GetFullChannelRequest(entity))

        title = entity.title or ""
        description = full.full_chat.about or ""
        participants = full.full_chat.participants_count or 0

        # --- quick semantic filter ---
        if not text_contains_keywords(title + description, CITY_KEYWORDS):
            return

        if not text_contains_keywords(title + description, RENT_KEYWORDS):
            return

        # --- activity check ---
        last_message_date = None
        async for msg in tg_client.iter_messages(entity, limit=1):
            last_message_date = msg.date

        record = {
            "username": channel_username,
            "title": title,
            "description": description,
            "participants_count": participants,
            "last_message_at": last_message_date.isoformat() if last_message_date else None,
            "stage": "raw",
            "source": "telegram",
            "city": "Tyumen"
        }

        supabase.table("channels").upsert(record).execute()
        print(f"[OK] {channel_username}")

    except Exception as e:
        print(f"[ERROR] {channel_username} -> {e}")

# =========================
# ENTRYPOINT
# =========================
async def main():
    await tg_client.start()

    # 🔹 СЮДА ТЫ ДОБАВЛЯЕШЬ КАНАЛЫ ДЛЯ РАЗВЕДКИ
    seed_channels = [
        "https://t.me/tyumen_zhilye_arenda_snyat",
        "nedvizhimost_tyumen",
        "@nedvizhimost_tyumen",
        #"tyumen_realty",
    ]

    for ch in seed_channels:
        await process_channel(ch)

    await tg_client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
