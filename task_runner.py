import os, re, asyncio, json, requests, hashlib
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- КЛЮЧИ ---
api_id = int(os.environ.get("TG_API_ID", 0))
api_hash = os.environ.get("TG_API_HASH", "")
session_str = os.environ.get("TG_SESSION_STRING", "")
supabase_url = os.environ.get("SUPABASEE_URL", "")
supabase_key = os.environ.get("SUPABASEE_KEY", "")
gemini_key = os.environ.get("GEMINI_KEY", "")

supabase = create_client(supabase_url, supabase_key)

async def analyze_with_ai(text, city):
    await asyncio.sleep(2) # Пауза для обхода лимита 15 RPM
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    prompt = f"Ты аналитик аренды в г. {city}. Извлеки данные: {{'price': int, 'address': str, 'phone': str, 'is_offer': bool}}. Текст: {text}"
    try:
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
        res_json = resp.json()
        if 'candidates' not in res_json: return None
        raw = res_json['candidates'][0]['content']['parts'][0]['text']
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        return json.loads(match.group()) if match else None
    except: return None

def parse_with_regex(text):
    clean_text = text.split('⚡️')[0].split('Подпишись')[0].strip()
    text_low = clean_text.lower()
    
    # 1. ЯДРО
    is_rent = any(word in text_low for word in ['сдам', 'аренда', 'собственник', 'сдается', 'студия', 'комната'])

    # 2. ТЕЛЕФОН
    phone_match = re.search(r'(?:\+?7|8)?[\s\-]?\(?9\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}', clean_text)
    phone = re.sub(r'[^\d]', '', phone_match.group(0)) if phone_match else None
    if phone and len(phone) == 10: phone = "7" + phone

    # 3. ЦЕНА (Игнорируем кв.м)
    price = 0
    price_pattern = r'(\d[\d\s\.]*)\s*(?:тыс|т\.р|тр|руб|₽|р\.|\s\+|\sкв|в месяц|включено)'
    for m in re.finditer(price_pattern, clean_text, re.IGNORECASE):
        # Если после числа "кв", "м", "эт" — это не цена
        context_after = clean_text[m.end():m.end()+12].lower()
        if any(x in context_after for x in ['кв', ' м', 'эт']): continue
        
        val = int(re.sub(r'[\s\.]', '', m.group(1)))
        if val <= 350: val *= 1000
        if 5000 <= val <= 400000:
            if 'залог' not in clean_text[max(0, m.start()-20):m.start()].lower():
                price = val; break

    # 4. АДРЕС
    address = None
    addr_markers = ['ул.', 'ул ', 'улица', 'пр.', 'жк', 'мкр', 'тракт', 'адрес', 'район']
    for line in clean_text.split('\n'):
        if any(m in line.lower() for m in addr_markers):
            if not any(p in line.lower() for p in ['руб', 'тыс', '₽', 'цена']):
                address = line.strip()[:100]; break
    
    return {"is_rent": is_rent, "phone": phone, "price": price, "address": address, "clean_text": clean_text}

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    res = supabase.table("channels_passport").select("*").eq("status", "active").execute()
    
    for ch in res.data:
        city = ch.get('city', 'Тюмень')
        print(f"📡 Сбор: {ch['channel_id']}")
        
        async for msg in client.iter_messages(ch['channel_id'].replace('@',''), limit=150):
            if not msg.text or msg.date < (datetime.now(timezone.utc) - timedelta(days=2)): continue

            reg = parse_with_regex(msg.text)
            if not reg['is_rent']: continue 

            final_data = reg
            method = "regex"

            # Если Regex не нашел Адрес или Цену — зовем ИИ
            if reg['price'] == 0 or not reg['address']:
                print(f"   🔍 #{msg.id}: Regex не уверен. ИИ...")
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
