import os, re, asyncio, json, requests, hashlib
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- КЛЮЧИ (СТРОГО ПО ТВОЕМУ СПИСКУ) ---
API_ID = os.environ.get('TG_API_ID')
API_HASH = os.environ.get('TG_API_HASH')
SESSION_STRING = os.environ.get('TG_SESSION_STRING')
GEMINI_KEY = os.environ.get('GEMINI_KEY')
SUPABASE_URL = os.environ.get('SUPABASEE_URL')
SUPABASE_KEY = os.environ.get('SUPABASEE_KEY')

# Инициализация Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

async def analyze_with_ai(text, city):
    """ИИ-Агент: включается, если Regex не нашел данные"""
    await asyncio.sleep(4) # Защита от лимитов (15 RPM)
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    prompt = f"Ты аналитик аренды в г. {city}. Извлеки данные: {{'price': int, 'address': str, 'phone': str, 'is_offer': bool}}. Текст: {text}"
    
    try:
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=20)
        res_json = resp.json()
        if 'candidates' not in res_json: return None
        raw = res_json['candidates'][0]['content']['parts'][0]['text']
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        return json.loads(match.group()) if match else None
    except: return None

def parse_with_regex(text):
    """Бинарное Ядро и быстрый Хвост"""
    clean_text = text.split('⚡️')[0].split('Подпишись')[0].strip()
    text_low = clean_text.lower()
    
    # 1. ЯДРО (Берем/Нет)
    rent_keywords = ['сдам', 'аренда', 'собственник', 'сдается', 'студия', 'комната', 'хозяин']
    is_rent = any(word in text_low for word in rent_keywords)

    # 2. ТЕЛЕФОН
    digits = re.sub(r'[^\d]', '', clean_text)
    phone_match = re.search(r'(7|8)?9\d{9}', digits)
    phone = phone_match.group(0) if phone_match else None

    # 3. ЦЕНА (Защита от кв.м)
    price = 0
    price_pattern = r'(\d[\d\s\.]*)\s*(?:тыс|т\.р|тр|руб|₽|р\.|\s\+|\sкв|в месяц)'
    for m in re.finditer(price_pattern, clean_text, re.IGNORECASE):
        # Если после числа "кв", "м" или "эт" — это не цена
        context_after = clean_text[m.end():m.end()+12].lower()
        if any(x in context_after for x in ['кв', ' м', 'эт']): continue
        
        val = int(re.sub(r'[\s\.]', '', m.group(1)))
        if val <= 350: val *= 1000
        if 5000 <= val <= 400000:
            if 'залог' not in clean_text[max(0, m.start()-20):m.start()].lower():
                price = val; break

    # 4. АДРЕС
    address = None
    for line in clean_text.split('\n'):
        if any(m in line.lower() for m in ['ул.', 'улица', 'жк', 'мкр', 'пр.', 'адрес']):
            if not any(p in line.lower() for p in ['руб', 'тыс', '₽']):
                address = line.strip()[:100]; break
    
    return {"is_rent": is_rent, "phone": phone, "price": price, "address": address, "clean_text": clean_text}

async def run_task():
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    await client.start()

    # Берем активные каналы
    res_ch = supabase.table("channels_passport").select("*").eq("status", "active").execute()
    
    for ch in res_ch.data:
        city = ch.get('city', 'Тюмень')
        print(f"📡 Сбор: {ch['channel_id']}")
        
        async for msg in client.iter_messages(ch['channel_id'].replace('@',''), limit=100):
            if not msg.text or msg.date < (datetime.now(timezone.utc) - timedelta(days=2)): continue

            reg = parse_with_regex(msg.text)
            if not reg['is_rent']: continue 

            final_data = reg
            method = "regex"

            # Если код не нашел Адрес или Цену — зовем ИИ
            if reg['price'] == 0 or not reg['address']:
                print(f"   🔍 #{msg.id}: Regex не уверен. Зовем ИИ...")
                ai = await analyze_with_ai(reg['clean_text'], city)
                if ai and ai.get('is_offer'):
                    final_data, method = ai, "ai_assisted"
                elif reg['price'] > 0: method = "regex_partial"
                else: continue

            try:
                content_hash = hashlib.md5(reg['clean_text'].encode()).hexdigest()
                supabase.table("rposts").insert({
                    "channel_id": ch['channel_id'],
                    "post_text": reg['clean_text'][:1000],
                    "price": final_data['price'],
                    "address": final_data['address'] or f"{city}",
                    "phone": final_data['phone'] or "Не указан",
                    "raw_json": {"method": method, "hash": content_hash}
                }).execute()
                print(f"   ✅ #{msg.id} [{method}]: {final_data['price']} р. | {final_data['address']}")
            except: continue

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
