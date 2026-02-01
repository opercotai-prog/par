import os, re, asyncio, json, requests
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# Ключи
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_str = os.getenv("TG_SESSION_STRING")
supabase_url = os.getenv("SUPABASEE_URL")
supabase_key = os.getenv("SUPABASEE_KEY")
gemini_key = os.getenv("GEMINI_KEY")

supabase = create_client(supabase_url, supabase_key)

def analyze_with_ai(text, city):
    # Оставляем твою модель
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    prompt = f"Извлеки данные (г. {city}): {text}. Верни строго JSON: {{'price': int, 'address': str, 'phone': str, 'is_offer': bool}}"
    try:
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
        res_json = resp.json()
        if 'candidates' not in res_json:
            print(f"      ❌ Ошибка ИИ: {res_json}")
            return None
        raw = res_json['candidates'][0]['content']['parts'][0]['text']
        return json.loads(re.sub(r'```json|```', '', raw).strip())
    except Exception as e:
        print(f"      ⚠️ ИИ упал: {e}")
        return None

def parse_with_regex(text):
    # Убираем только хвост по ⚡️
    clean_text = text.split('⚡️')[0].split('Подпишись')[0].strip()
    text_low = clean_text.lower()
    
    # 1. ЯДРО: Ключи аренды
    rent_keywords = ['сдам', 'аренда', 'собственник', 'сдается', 'хозяин', 'длительный']
    is_rent = any(word in text_low for word in rent_keywords)

    # 2. ТЕЛЕФОН: Ищем 10-11 цифр (необязательно)
    digits = re.sub(r'[^\d]', '', clean_text)
    phone_match = re.search(r'(7|8)?9\d{9}', digits)
    phone = phone_match.group(0) if phone_match else None

    # 3. ЦЕНА: Ищем число + маркер
    price = 0
    price_pattern = r'(\d[\d\s\.]*)\s*(?:тыс|т\.р|тр|руб|₽|р\.|\s\+|\sкв|в месяц)'
    for m in re.finditer(price_pattern, clean_text, re.IGNORECASE):
        val_str = re.sub(r'[\s\.]', '', m.group(1))
        if not val_str: continue
        val = int(val_str)
        if 10 <= val <= 300: val *= 1000
        if 5000 <= val <= 350000:
            if 'залог' not in clean_text[max(0, m.start()-20):m.start()].lower():
                price = val; break

    # 4. АДРЕС: Ищем по маркерам
    address = None
    for line in clean_text.split('\n'):
        if any(m in line.lower() for m in ['ул.', 'улица', 'пр.', 'жк', 'мкр', 'тракт']):
            if not any(p in line.lower() for p in ['руб', 'тыс', '₽', 'цена']):
                address = line.strip()[:100]; break

    return {"is_rent": is_rent, "phone": phone, "price": price, "address": address, "clean_text": clean_text}

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

            # ГЛАВНОЕ ИСПРАВЛЕНИЕ: Телефон больше не обязателен для Regex-пути
            # Если Regex нашел Цену и Адрес — этого достаточно
            if reg['price'] > 0 and reg['address']:
                data = reg
                method = "regex"
            else:
                # Если чего-то не хватает, но это пост про аренду — зовем ИИ
                print(f"   🔍 #{msg.id}: Regex не всё нашел (Цена:{reg['price']} Адр:{reg['address']}). ИИ...")
                ai = analyze_with_ai(reg['clean_text'], city)
                if ai and ai.get('is_offer'):
                    data = ai
                    method = "ai_assisted"
                else: continue

            try:
                supabase.table("rposts").insert({
                    "channel_id": ch['channel_id'],
                    "post_text": reg['clean_text'][:1000],
                    "price": data['price'],
                    "address": data['address'] or f"{city} (см. текст)",
                    "phone": data['phone'] or "Не указан",
                    "raw_json": {"method": method}
                }).execute()
                print(f"   ✅ #{msg.id} [{method}]: {data['price']} р. | {data['address']}")
            except Exception as e: 
                continue

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
