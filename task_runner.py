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
    """ИИ-Агент: включается в работу, когда код не уверен"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    
    prompt = f"Ты аналитик аренды в г. {city}. Извлеки данные из текста. is_offer=true только если сдают жилье. price=цена в месяц (не залог, не метры). address=улица/ЖК (без мусора). phone=формат 79XXXXXXXXX. Текст: {text}. Верни СТРОГИЙ JSON: {{'price': int, 'address': str, 'phone': str, 'is_offer': bool}}"
    
    try:
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
        raw = resp.json()['candidates'][0]['content']['parts'][0]['text']
        return json.loads(re.sub(r'```json|```', '', raw).strip())
    except Exception as e:
        print(f"      ⚠️ Ошибка ИИ-агента: {e}")
        return None

def parse_with_regex(text):
    """Быстрое сито (Regex)"""
    clean_text = text.split('⚡️')[0].split('Подпишись')[0].strip()
    
    # Телефон: ищем 10-11 цифр, не склеенных с ценой
    phone_match = re.search(r'(?:\+?7|8)?[\s\-]?\(?9\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}', clean_text)
    phone = re.sub(r'[^\d]', '', phone_match.group(0)) if phone_match else None
    if phone and len(phone) == 10: phone = "7" + phone

    # Цена: ищем число рядом с маркерами валюты
    price = 0
    price_pattern = r'(\d[\d\s\.]*)\s*(?:тыс|т\.р|тр|руб|₽|р\.|\s\+|\sкв|в месяц)'
    for m in re.finditer(price_pattern, clean_text, re.IGNORECASE):
        val = int(re.sub(r'[\s\.]', '', m.group(1)))
        if 'кв' in clean_text[m.end():m.end()+10].lower(): continue
        if 10 <= val <= 300: val *= 1000
        if 5000 <= val <= 350000:
            if 'залог' not in clean_text[max(0, m.start()-20):m.start()].lower():
                price = val; break

    # Адрес: только явные маркеры
    address = None
    for line in clean_text.split('\n'):
        if any(m in line.lower() for m in ['ул.', 'улица', 'пр.', 'жк', 'мкр', 'тракт']):
            if not any(p in line.lower() for p in ['руб', 'тыс', '₽']):
                address = line.strip()[:100]; break

    return {"phone": phone, "price": price, "address": address, "clean_text": clean_text}

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    res = supabase.table("channels_passport").select("*").eq("status", "active").execute()
    
    for ch in res.data:
        city = ch.get('city', 'Тюмень')
        print(f"📡 Канал: {ch['channel_id']}")
        
        async for msg in client.iter_messages(ch['channel_id'].replace('@',''), limit=100):
            if not msg.text or msg.date < (datetime.now(timezone.utc) - timedelta(days=2)): continue

            # 1. Сначала Regex
            reg = parse_with_regex(msg.text)
            
            # 2. Бинарное решение: звать ИИ или нет?
            is_valid = reg['phone'] and reg['price'] > 0 and reg['address']
            
            if is_valid:
                data, method = reg, "regex"
            else:
                print(f"   🔍 #{msg.id}: Данные неполные. Включаем ИИ-агента...")
                ai = analyze_with_ai(reg['clean_text'], city)
                if ai and ai.get('is_offer'):
                    data, method = ai, "ai_assisted"
                else:
                    continue # Мусор

            # 3. Запись
            try:
                supabase.table("rposts").insert({
                    "channel_id": ch['channel_id'],
                    "post_text": reg['clean_text'][:1000],
                    "price": data['price'],
                    "address": data['address'],
                    "phone": data['phone'],
                    "raw_json": {"method": method}
                }).execute()
                print(f"   ✅ #{msg.id} [{method}]: {data['price']} р. | {data['address']}")
            except: continue

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
