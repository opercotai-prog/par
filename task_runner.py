import os, re, asyncio, json, requests, hashlib
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- НАСТРОЙКИ ---
api_id = int(os.environ.get("TG_API_ID", 0))
api_hash = os.environ.get("TG_API_HASH", "")
session_str = os.environ.get("TG_SESSION_STRING", "")
supabase_url = os.environ.get("SUPABASEE_URL", "")
supabase_key = os.getenv("SUPABASEE_KEY", "")
gemini_key = os.environ.get("GEMINI_KEY", "")

supabase = create_client(supabase_url, supabase_key)

def analyze_with_ai(text, city):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    # ОБНОВЛЕННЫЙ ПРОМПТ
    prompt = f"""
    Ты аналитик аренды жилья в г. {city}. Извлеки данные из текста.
    - is_offer: true только если сдают КВАРТИРУ, СТУДИЮ или КОМНАТУ.
    - price: только месячная аренда (целое число, не залог).
    - address: только улица/дом/ЖК. Если адреса нет, пиши просто "{city}".
    - phone: строго 11 цифр 79XXXXXXXXX.
    Текст: {text}
    Верни JSON: {{"price": int, "address": "str", "phone": "str", "is_offer": bool}}
    """
    try:
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
        raw = resp.json()['candidates'][0]['content']['parts'][0]['text']
        return json.loads(re.sub(r'```json|```', '', raw).strip())
    except: return None

def parse_with_regex(text):
    clean_text = text.split('⚡️')[0].split('Подпишись')[0].strip()
    lines = [l.strip() for l in clean_text.split('\n') if len(l.strip()) > 5]
    text_low = clean_text.lower()
    
    # 1. ЯДРО (ДОБАВЛЕНЫ СТУДИИ И КОМНАТЫ)
    rent_keywords = ['сдам', 'аренда', 'собственник', 'сдается', 'хозяин', 'длительный', 'студия', 'студию', 'комната', 'комнату', 'евродвушка']
    if not any(word in text_low for word in rent_keywords): return {"is_rent": False}

    # 2. ТЕЛЕФОН
    phone_match = re.search(r'(?:\+?7|8)?[\s\-]?\(?9\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}', clean_text)
    phone = re.sub(r'[^\d]', '', phone_match.group(0)) if phone_match else None
    if phone and len(phone) == 10: phone = "7" + phone
    elif phone and len(phone) == 11 and phone.startswith('8'): phone = "7" + phone[1:]

    # 3. ЦЕНА (УЛУЧШЕН ПОИСК БЕЗ ПРОБЕЛОВ)
    price = 0
    price_pattern = r'(\d[\d\s\.]*)\s*(?:тыс|т\.р|тр|руб|₽|р\.|\s\+|\sкв|в месяц)'
    for m in re.finditer(price_pattern, clean_text.replace('рублей',' руб'), re.IGNORECASE):
        if re.search(r'(?:д\.|корп|ул)\.?\s*$', clean_text[:m.start()].lower()): continue
        val = int(re.sub(r'[\s\.]', '', m.group(1)))
        if val <= 350: val *= 1000
        if 5000 <= val <= 400000:
            if 'залог' not in clean_text[max(0, m.start()-20):m.start()].lower():
                price = val; break

    # 4. АДРЕС
    address = None
    garbage = ['без животных', 'оплата', 'залог', 'собственник', 'сдам', 'евродвушка']
    for line in lines:
        line_low = line.lower()
        if any(m in line_low for m in ['ул.', 'ул ', 'жк', 'мкр', 'тракт']):
            if not any(g in line_low for g in garbage):
                address = line[:100].strip(); break
    
    return {"is_rent": True, "phone": phone, "price": price, "address": address, "clean_text": clean_text}

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    res_ch = supabase.table("channels_passport").select("*").eq("status", "active").execute()
    
    for ch in res_ch.data:
        city = ch.get('city', 'Тюмень')
        print(f"📡 Канал: {ch['channel_id']}")
        
        async for msg in client.iter_messages(ch['channel_id'].replace('@',''), limit=150):
            if not msg.text or msg.date < (datetime.now(timezone.utc) - timedelta(days=3)): continue

            reg = parse_with_regex(msg.text)
            if not reg.get('is_rent'): continue 

            # ГИБРИДНЫЙ ВЫБОР (КОМНАТЫ < 10к ИДУТ К ИИ)
            if reg['price'] < 10000 or not reg['address'] or reg['price'] == 0:
                print(f"   🔍 #{msg.id}: Regex не уверен. Зовем ИИ...")
                ai = analyze_with_ai(reg['clean_text'], city)
                if ai and ai.get('is_offer'):
                    data, method = ai, "ai_assisted"
                elif reg['price'] > 0: data, method = reg, "regex_partial"
                else: continue
            else:
                data, method = reg, "regex"

            content_hash = hashlib.md5(reg['clean_text'].encode()).hexdigest()
            try:
                supabase.table("rposts").insert({
                    "channel_id": ch['channel_id'],
                    "post_text": reg['clean_text'][:1000],
                    "price": data['price'],
                    "address": data['address'] or f"{city}",
                    "phone": data['phone'] or "Не указан",
                    "raw_json": {"method": method, "hash": content_hash}
                }).execute()
                print(f"   ✅ #{msg.id} [{method}]: {data['price']} р. | {data['address']}")
            except: continue

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
