import os
import asyncio
import re
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetHistoryRequest
from supabase import create_client

# =========================
# НАСТРОЙКИ
# =========================

CHANNELS = [
    "arendakvartirkalingrad",
    # добавь ещё 4 канала
]

CITY = "Москва"
POST_LIMIT_PER_RUN = 50   # максимум новых постов за запуск

# =========================
# ENV
# =========================

API_ID = os.getenv("TG_API_ID")
API_HASH = os.getenv("TG_API_HASH")
SESSION_STRING = os.getenv("TG_SESSION_STRING")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not all([API_ID, API_HASH, SESSION_STRING, SUPABASE_URL, SUPABASE_KEY]):
    raise RuntimeError("❌ Не заданы переменные окружения")

# =========================
# CLIENTS
# =========================

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

client = TelegramClient(
    StringSession(SESSION_STRING),
    int(API_ID),
    API_HASH
)

# =========================
# ПАРСЕРЫ (без ИИ)
# =========================

def parse_price(text):
    m = re.search(r'(\d{2,6})\s*(₽|руб)', text.replace(" ", ""))
    return int(m.group(1)) if m else None

def parse_rooms(text):
    t = text.lower()
    if "студ" in t:
        return "studio"
    if "1к" in t or "однокомнат" in t:
        return "1"
    if "2к" in t or "двухкомнат" in t:
        return "2"
    if "3к" in t:
        return "3"
    return None

def parse_phone(text):
    m = re.search(r'(\+7|8)\d{10}', text.replace(" ", ""))
    if not m:
        return None
    phone = m.group(0)
    if phone.startswith("8"):
        phone = "7" + phone[1:]
    return phone.replace("+", "")

# =========================
# ОСНОВНАЯ ЛОГИКА
# =========================

async def parse_channel(channel):
    print(f"📺 Канал: {channel}")

    offset = supabase.table("parser_offsets") \
        .select("last_message_id") \
        .eq("source_channel", channel) \
        .execute()

    last_id = offset.data[0]["last_message_id"] if offset.data else 0

    history = await client(GetHistoryRequest(
        peer=channel,
        limit=POST_LIMIT_PER_RUN,
        offset_id=last_id,
        offset_date=None,
        max_id=0,
        min_id=0,
        add_offset=0,
        hash=0
    ))

    max_seen_id = last_id
    saved = 0

    for msg in history.messages:
        if not msg.text:
            continue
        if msg.id <= last_id:
            continue

        record = {
            "platform": "telegram",
            "source_channel": channel,
            "external_id": str(msg.id),
            "city": CITY,
            "price": parse_price(msg.text),
            "rooms": parse_rooms(msg.text),
            "contact_phone": parse_phone(msg.text),
            "raw_text": msg.text[:3000],
            "is_agent": False,
            "is_published": True
        }

        try:
            supabase.table("ads").insert(record).execute()
            saved += 1
            max_seen_id = max(max_seen_id, msg.id)
        except Exception:
            pass

    if max_seen_id > last_id:
        supabase.table("parser_offsets").upsert({
            "source_channel": channel,
            "last_message_id": max_seen_id
        }).execute()

    print(f"✅ Сохранено: {saved}")

# =========================
# MAIN
# =========================

async def main():
    await client.connect()

    if not await client.is_user_authorized():
        raise RuntimeError("❌ StringSession не авторизована")

    me = await client.get_me()
    print("👤 Авторизован как:", me.username or me.id)

    for ch in CHANNELS:
        await parse_channel(ch)

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
