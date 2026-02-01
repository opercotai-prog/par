import os, re, asyncio, hashlib, json, requests
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- КЛЮЧИ ---
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_str = os.getenv("TG_SESSION_STRING")
supabase_url = os.getenv("SUPABASEE_URL")
supabase_key = os.getenv("SUPABASEE_KEY")
gemini_key = os.getenv("GEMINI_KEY")

supabase = create_client(supabase_url, supabase_key)

def analyze_with_ai(text, city):
    """ИИ-арбитр для спорных постов"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    prompt = f"Извлечи данные по аренде (г. {city}). Текст: {text}. Верни строго JSON: {{'price': int, 'address': str, 'phone': str, 'is_offer': bool}}"
    try:
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=10)
        raw = resp.json()['candidates'][0]['content']['parts'][0]['text']
        return json.loads(re.sub(r'```json|```', '', raw).strip())
    except: return None

def parse_with_regex(text):
    """Универсальное 'сито' (Regex)"""
    # 0. Отрезаем мусор по маркеру ⚡️
    clean_text = text.split('⚡️')[0].split('Подпишись')[0].replace('\xa0', ' ').strip()
    
    # 1. ТЕЛЕФОН (Ядро)
    digits = re.sub(r'[^\d]', '', clean_text)
    phone_match = re.search(r'(7|8)?9\d{9}', digits)
    phone = phone_match.group(0) if phone_match else None

    # 2. ЦЕНА (Хвост)
    price = 0
    price_pattern = r'(\d[\d\s\.]*)\s*(?:тыс|т\.р|тр|руб|₽|р\.|\s\+|\sкв|в месяц)'
    for m in re.finditer(price_pattern, clean_text, re.IGNORECASE):
        val = int(re.sub(r'[\s\.]', '', m.group(1)))
        # Исключаем площадь (кв.м)
        if 'кв' in clean_text[m.end():m.end()+10].lower(): continue
        if 10 <= val <= 250: val *= 1000 # 25 -> 25000
        if 5000 <= val <= 350000:
            if 'залог' not in clean_text[max(0, m.start()-20):m.start()].lower():
                price = val; break

    # 3. АДРЕС (Хвост)
    address = None
    addr_markers = ['ул.', 'улица', 'пр.', 'жк', 'мкр', 'тракт', 'район', 'адресу']
    for line in clean_text.split('\n'):
        if any(m in line.lower() for m in addr_markers) and not any(p in line.lower() for p in ['руб', 'тыс', '₽']):
            address = line.strip()[:100]; break

    return {"phone": phone, "price": price, "address": address, "clean_text": clean_text}

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    # Берем активные каналы из паспорта
    res = supabase.table("channels_passport").select("*").eq("status", "active").execute()
    
    for ch in res.data:
        city = ch.get('city', 'Тюмень')
        print(f"📡 Сбор: {ch['channel_id']}")
        
        async for msg in client.iter_messages(ch['channel_id'].replace('@',''), limit=100):
            if not msg.text or msg.date < (datetime.now(timezone.utc) - timedelta(days=2)): break

            # ШАГ 1: Пытаемся взять кодом
            res_reg = parse_with_regex(msg.text)
            
            # ШАГ 2: БИНАРНАЯ ЛОГИКА
            method = "regex"
            final_data = res_reg

            # Если код нашел телефон, но потерял цену или адрес — зовем ИИ
            if res_reg['phone'] and (res_reg['price'] == 0 or not res_reg['address']):
                print(f"   🔍 Пост {msg.id}: Код не уверен. Зовем ИИ...")
                ai_res = analyze_with_ai(res_reg['clean_text'], city)
                if ai_res and ai_res.get('is_offer'):
                    final_data = ai_res
                    method = "ai_assisted"
                else: continue # Если и ИИ не подтвердил оффер — в мусор

            # Если нет телефона и ИИ не помог — в мусор
            if not final_data.get('phone') or final_data.get('phone') == "Не указан": continue

            # ШАГ 3: ЗАПИСЬ
            try:
                supabase.table("rposts").insert({
                    "channel_id": ch['channel_id'],
                    "post_text": res_reg['clean_text'][:1000],
                    "price": final_data['price'],
                    "address": final_data['address'],
                    "phone": final_data['phone'],
                    "raw_json": {"method": method}
                }).execute()
                print(f"   ✅ {msg.id} ({method}): {final_data['price']} р. | {final_data['address']}")
            except: continue

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
