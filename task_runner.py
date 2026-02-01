import os, re, asyncio
from datetime import datetime, timezone
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# Ключи
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_str = os.getenv("TG_SESSION_STRING")
supabase_url = os.getenv("SUPABASEE_URL")
supabase_key = os.getenv("SUPABASEE_KEY")

supabase = create_client(supabase_url, supabase_key)

def parse_post_no_ai(text):
    clean_text = text.replace('\xa0', ' ').strip()
    
    # --- 1. ЯДРО (ТЕЛЕФОН) ---
    digits_only = re.sub(r'[^\d]', '', clean_text)
    phone_match = re.search(r'(7|8)9\d{9}', digits_only)
    if not phone_match: return None
    phone = phone_match.group(0)

    # --- 2. ЯДРО (МАРКЕРЫ) ---
    rent_keywords = ['сдам', 'сдается', 'сдаётся', 'собственник', 'аренда', 'студия', 'евродвушка']
    if not any(word in clean_text.lower() for word in rent_keywords):
        return None

    # --- 3. ХВОСТ (ЦЕНА) ---
    price = 0
    # Ищем числа: "28", "28 000", "28000" рядом с руб/т.р/+/в месяц
    price_pattern = r'(\d[\d\s]{1,6})\s*(?:тыс|т\.р|тр|руб|₽|р\.|\s\+|\sкв|в месяц)'
    matches = list(re.finditer(price_pattern, clean_text, re.IGNORECASE))
    
    for match in matches:
        val_str = re.sub(r'\s+', '', match.group(1))
        val = int(val_str)
        if 10 <= val <= 200: val *= 1000 # из "28" в "28000"
        
        if 5000 <= val <= 200000:
            context = clean_text[max(0, match.start()-20):match.start()].lower()
            if 'залог' not in context and 'депозит' not in context:
                price = val
                break

    # --- 4. ХВОСТ (АДРЕС) ---
    address = "Тюмень (адрес в тексте)"
    addr_markers = ['ул.', 'улица', 'пр.', 'проспект', 'мкр', 'жк', 'адресу', 'район', 'тракт', 'беловежская', 'мельникайте']
    lines = clean_text.split('\n')
    for line in lines:
        if any(marker in line.lower() for marker in addr_markers):
            address = re.sub(r'^[^\w\sа-яА-Я]+', '', line).strip()[:100]
            break

    return {"price": price, "address": address, "phone": phone}

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    channel_id = "arendatumen72rus"
    start_date = datetime(2026, 1, 28, tzinfo=timezone.utc)
    end_date = datetime(2026, 2, 1, tzinfo=timezone.utc)

    print(f"🚀 Сбор @{channel_id} (БЕЗ ИИ)...")

    count = 0
    saved = 0
    async for msg in client.iter_messages(channel_id, limit=200):
        if msg.date < start_date: break
        if msg.date > end_date: continue
        if not msg.text: continue

        count += 1
        res = parse_post_no_ai(msg.text)
        
        if res:
            try:
                supabase.table("rposts").insert({
                    "channel_id": f"@{channel_id}",
                    "post_text": msg.text[:500], # обрезаем для базы
                    "price": res['price'],
                    "address": res['address'],
                    "phone": res['phone']
                }).execute()
                print(f"✅ Сохранено: {res['price']} руб. | {res['address']}")
                saved += 1
            except: continue

    print(f"🏁 Итог: Проверено {count}, Сохранено {saved}")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
