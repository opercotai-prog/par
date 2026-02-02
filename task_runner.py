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

def analyze_with_ai(text, city):
    # Используем 1.5-flash как самую стабильную
    url =f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    prompt = f"Извлеки данные (г. {city}): {text}. Верни строго JSON: {{'price': int, 'address': str, 'phone': str, 'is_offer': bool}}"
    try:
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
        res_json = resp.json()
        if 'candidates' not in res_json:
            print(f"      ⚠️ Ошибка API: {res_json.get('error', {}).get('message', 'Unknown')}")
            return None
        raw = res_json['candidates'][0]['content']['parts'][0]['text']
        # Более надежная очистка JSON
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        return json.loads(match.group()) if match else None
    except: return None

def parse_with_regex(text):
    clean_text = text.split('⚡️')[0].split('Подпишись')[0].strip()
    lines = [l.strip() for l in clean_text.split('\n') if len(l.strip()) > 5]
    text_low = clean_text.lower()
    
    # 1. ЯДРО
    rent_keywords = ['сдам', 'аренда', 'собственник', 'сдается', 'хозяин', 'студия', 'комната']
    is_rent = any(word in text_low for word in rent_keywords)

    # 2. ТЕЛЕФОН
    phone_match = re.search(r'(?:\+?7|8)?[\s\-]?\(?9\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}', clean_text)
    phone = re.sub(r'[^\d]', '', phone_match.group(0)) if phone_match else None
    if phone and len(phone) == 10: phone = "7" + phone
    elif phone and len(phone) == 11 and phone.startswith('8'): phone = "7" + phone[1:]

    # 3. ЦЕНА
    price = 0
    price_pattern = r'(\d[\d\s\.]*)\s*(?:тыс|т\.р|тр|руб|₽|р\.|\s\+|\sкв|в месяц)'
    for m in re.finditer(price_pattern, clean_text, re.IGNORECASE):
        val = int(re.sub(r'[\s\.]', '', m.group(1)))
        if val <= 350: val *= 1000
        if 5000 <= val <= 400000:
            if 'залог' not in clean_text[max(0, m.start()-20):m.start()].lower():
                price = val; break

    # 4. АДРЕС (Добавлен маркер 'адресу')
    address = None
    addr_markers = ['ул.', 'ул ', 'улица', 'пр.', 'жк', 'мкр', 'тракт', 'адресу']
    for line in lines:
        if any(m in line.lower() for m in addr_markers):
            if not any(p in line.lower() for p in ['руб', 'тыс', '₽']):
                address = line.strip()[:100]; break
    
    return {"is_rent": is_rent, "phone": phone, "price": price, "address": address, "clean_text": clean_text, "lines": lines}

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    res = supabase.table("channels_passport").select("*").eq("status", "active").execute()
    
    for ch in res.data:
        city = ch.get('city', 'Тюмень')
        print(f"📡 Канал: {ch['channel_id']}")
        
        async for msg in client.iter_messages(ch['channel_id'].replace('@',''), limit=150):
            if not msg.text or msg.date < (datetime.now(timezone.utc) - timedelta(days=2)): continue

            reg = parse_with_regex(msg.text)
            if not reg['is_rent']: continue 

            final_data = reg
            method = "regex"

            # Вызываем ИИ только если НЕТ адреса или цены
            if reg['price'] == 0 or not reg['address']:
                print(f"   🔍 #{msg.id}: Regex не уверен. ИИ...")
                ai = analyze_with_ai(reg['clean_text'], city)
                if ai and ai.get('is_offer'):
                    final_data = ai
                    method = "ai_assisted"
                elif reg['price'] > 0:
                    # Если ИИ упал, но цена есть — берем Regex и 2-ю строку как адрес
                    method = "regex_partial"
                    if not reg['address'] and len(reg['lines']) > 1:
                        final_data['address'] = reg['lines'][1]
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
