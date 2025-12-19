import os
import re
import asyncio
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from supabase import create_client

# =====================
# ENV (из GitHub Secrets)
# =====================
API_ID = int(os.getenv("TG_API_ID"))
API_HASH = os.getenv("TG_API_HASH")
SESSION = "session"

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# =====================
# Каналы (вставляешь вручную)
# =====================
CHANNELS = [
    "arendamsk_mo",
    #  "channel_2",
    #  "channel_3",
    # "channel_4",
    #  "channel_5",
]

CITY = "Москва"

# =====================
# Инициализация
# =====================
client = TelegramClient(SESSION, API_ID, API_HASH)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# =====================
# Простые парсеры (БЕЗ ИИ)
# =====================
def parse_price(text):
    m = re.search(r'(\d{2,6})\s*(₽|руб)', text.lower())
    return int(m.group(1)) if m else None

def parse_rooms(text):
    m = re.search(r'([1-5])\s*[-]?\s*(комн|к)', text.lower())
    return int(m.group(1)) if m else None

def parse_phone(text):
    m = re.search(r'(\+7|8)\s?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}', text)
    return m.group(0) if m else None

# =====================
# Основной парсинг
# =====================
async def parse_channel(channel):
    history = await client(GetHistoryRequest(
        peer=channel,
        limit=100,
        offset_date=None,
        offset_id=0,
        max_id=0,
        min_id=0,
        add_offset=0,
        hash=0
    ))

    for msg in history.messages:
        if not msg.text:
            continue

        text = msg.text

        record = {
            "platform": "telegram",
            "source_channel": channel,
            "external_id": str(msg.id),
            "city": CITY,

            "rooms": parse_rooms(text),
            "price": parse_price(text),
            "contact_phone": parse_phone(text),

            "raw_text": text[:3000],
            "is_agent": False,
            "is_published": True
        }

        supabase.table("ads").insert(record).execute()

# =====================
# RUN
# =====================
async def main():
    await client.start()
    for channel in CHANNELS:
        await parse_channel(channel)
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
