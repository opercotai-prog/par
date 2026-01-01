import os
import asyncio
from datetime import datetime, timezone

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.errors import UsernameNotOccupiedError, UsernameInvalidError

from supabase import create_client

# ==========================================
# 1. ENV
# ==========================================

API_ID = int(os.getenv("TG_API_ID"))
API_HASH = os.getenv("TG_API_HASH")
SESSION_STRING = os.getenv("TG_SESSION_STRING")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# ==========================================
# 2. КАНАЛЫ (ТЮМЕНЬ / АРЕНДА)
# ==========================================

CHANNEL_USERNAMES = [
    #"https://t.me/nedvizhimost_tyumen",
    "nedvizhimost_tyumen",
    #"https://t.me/tyumen_zhilye_arenda_snyat",
    "tyumen_zhilye_arenda_snyat",
    #"@tyumen_zhilye_arenda_snyat",
]

CITY = "Тюмень"
SOURCE = "manual_seed"

# ==========================================
# 3. CLIENTS
# ==========================================

tg_client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH
)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 4. CORE
# ==========================================

async def process_channel(username: str):
    print(f"\n🔍 Channel: {username}")

    try:
        entity = await tg_client.get_entity(username)
        full = await tg_client(GetFullChannelRequest(entity))

        record = {
            "username": username,
            "title": entity.title,
            "description": full.full_chat.about,
            "participants_count": full.full_chat.participants_count,
            "last_message_at": None,  # пока не читаем посты
            "city": CITY,
            "stage": "raw",
            "source": SOURCE,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }

        supabase.table("channels").upsert(
            record,
            on_conflict="username"
        ).execute()

        print(f"✅ saved | {entity.title} | members: {record['participants_count']}")

    except UsernameNotOccupiedError:
        print(f"⚠️ username not found: {username}")

    except UsernameInvalidError:
        print(f"⚠️ invalid username: {username}")

    except Exception as e:
        print(f"❌ error {username} -> {e}")

# ==========================================
# 5. MAIN
# ==========================================

async def main():
    print("🚀 START METADATA PARSER")
    await tg_client.start()

    for username in CHANNEL_USERNAMES:
        await process_channel(username)
        await asyncio.sleep(1.5)

    await tg_client.disconnect()
    print("\n🏁 DONE")

if __name__ == "__main__":
    asyncio.run(main())
