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
    text_for_search = clean_text.lower()
    
    # --- 1. ЯДРО (ТОЛЬКО КЛЮЧЕВЫЕ СЛОВА) ---
    rent_keywords = ['сдам', 'сдается', 'сдаётся', 'собственник', 'аренда', 'студия', 'хозяин', 'длительный', 'евродвушка']
    if not any(word in text_for_search for word in rent_keywords):
        return "ERR_NO_KEYWORDS", None

    # --- 2. ХВОСТ (СБОР ДАННЫХ) ---
    
    # Телефон (теперь не обязателен)
    digits_only = re.sub(r'[^\d]', '', clean_text)
    phone_match = re.search(r'9\d{9}', digits_only)
    phone = phone_match.group(0) if phone_match else "Не указан"

    # Цена
    price = 0
    price_pattern = r'(\d[\d\s\.]*)\s*(?:тыс|т\.р|тр|руб|₽|р\.|\s\+|\sкв|в месяц|все включено)'
    matches = list(re.finditer(price_pattern, clean_text, re.IGNORECASE))
    for match in matches:
        val_str = re.sub(r'[\s\.]', '', match.group(1))
        if not val_str: continue
        try:
            val = int(val_str)
            if 10 <= val <= 250: val *= 1000
            if 5000 <= val <= 300000:
                context = clean_text[max(0, match.start()-25):match.start()].lower()
                if 'залог' not in context and 'депозит' not in context:
                    price = val
                    break
        except: continue

    # Адрес
    address = "Тюмень"
    addr_markers = ['ул.', 'улица', 'пр.', 'проспект', 'мкр', 'жк', 'адресу', 'район', 'тракт', 'беловежская', 'мельникайте', 'подгорная']
    for line in clean_text.split('\n'):
        if any(marker in line.lower() for marker in addr_markers):
            address = line.strip()[:150]
            break

    return "OK", {"price": price, "address": address, "phone": phone}

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    channel_user = "arendatumen72rus"
    db_channel_id = "@arendatumen72rus" 
    
    # Даты (28 января - 2 февраля)
    start_date = datetime(2026, 1, 28, tzinfo=timezone.utc)
    end_date = datetime(2026, 2, 2, tzinfo=timezone.utc)

    print(f"🚀 Сбор {db_channel_id} (Бинарно по ключам)...")

    count = 0
    saved = 0
    
    async for msg in client.iter_messages(channel_user, limit=300):
        if not msg.text: continue
        if msg.date < start_date: break
        if msg.date > end_date: continue

        status, res = parse_post_no_ai(msg.text)
        count += 1
        
        if status == "OK":
            try:
                supabase.table("rposts").insert({
                    "channel_id": db_channel_id,
                    "post_text": msg.text.strip(),
                    "price": res['price'],
                    "address": res['address'],
                    "phone": res['phone']
                }).execute()
                print(f"✅ #{msg.id} Сохранено ({res['price']} руб.)")
                saved += 1
            except Exception as e:
                print(f"❌ #{msg.id} Ошибка БД: {e}")
        else:
            print(f"⚠️ #{msg.id} пропущен: {status}")

    print(f"🏁 Итог: Обработано {count}, Сохранено в rposts: {saved}")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
