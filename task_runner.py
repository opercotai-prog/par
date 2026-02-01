import os, re, asyncio, json, requests
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- КЛЮЧИ (через os.environ.get как в рабочем коде) ---
api_id = int(os.environ.get("TG_API_ID"))
api_hash = os.environ.get("TG_API_HASH")
session_str = os.environ.get("TG_SESSION_STRING")
supabase_url = os.environ.get("SUPABASEE_URL")
supabase_key = os.environ.get("SUPABASEE_KEY")
gemini_key = os.environ.get("GEMINI_KEY")

supabase = create_client(supabase_url, supabase_key)

def analyze_with_ai(text, city):
    """ИИ-Агент: вызывается только если цена не найдена кодом"""
    # Модель 2.5-flash, как ты просил
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
    """Максимально точный Regex парсинг без ИИ"""
    clean_text = text.split('⚡️')[0].split('Подпишись')[0].strip()
    lines = clean_text.split('\n')
    text_low = clean_text.lower()
    
    # 1. ЯДРО: Ключи
    rent_keywords = ['сдам', 'аренда', 'собственник', 'сдается', 'хозяин', 'длительный']
    is_rent = any(word in text_low for word in rent_keywords)

    # 2. ТЕЛЕФОН: ищем 10-11 цифр (не склеивая с ценой)
    phone_match = re.search(r'(?:\+?7|8)?[\s\-]?\(?9\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}', clean_text)
    phone = re.sub(r'[^\d]', '', phone_match.group(0)) if phone_match else None
    if phone and len(phone) == 10: phone = "7" + phone

    # 3. ЦЕНА
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

    # 4. АДРЕС: Маркеры или 2-я строка
    address = None
    addr_markers = ['ул.', 'ул ', 'улица', 'пр.', 'жк', 'мкр', 'тракт', 'адресу', 'д. ', 'корп']
    for line in lines:
        if any(m in line.lower() for m in addr_markers):
            if not any(p in line.lower() for p in ['руб', 'тыс', '₽']):
                address = line.strip()[:100]; break
    
    # Если адрес по маркерам не найден - берем 2-ю или 3-ю строку
    if not address and len(lines) > 1:
        for i in range(1, min(4, len(lines))):
            if len(lines[i]) > 10 and not any(k in lines[i].lower() for k in rent_keywords):
                address = lines[i].strip()[:100]; break

    return {"is_rent": is_rent, "phone": phone, "price": price, "address": address, "clean_text": clean_text}

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    # Берем каналы из паспорта
    res = supabase.table("channels_passport").select("*").eq("status", "active").execute()
    
    for ch in res.data:
        city = ch.get('city', 'Тюмень')
        print(f"📡 Канал: {ch['channel_id']}")
        
        async for msg in client.iter_messages(ch['channel_id'].replace('@',''), limit=150):
            if not msg.text or msg.date < (datetime.now(timezone.utc) - timedelta(days=3)): continue

            # ШАГ 1: Попытка Regex
            reg = parse_with_regex(msg.text)
            if not reg['is_rent']: continue 

            final_price = reg['price']
            final_address = reg['address']
            final_phone = reg['phone']
            method = "regex"

            # ШАГ 2: ИИ только если цена = 0
            if final_price == 0:
                print(f"   🔍 #{msg.id}: Нет цены. ИИ...")
                ai = analyze_with_ai(reg['clean_text'], city)
                if ai and ai.get('is_offer'):
                    final_price = ai.get('price') or final_price
                    final_address = ai.get('address') or final_address
                    final_phone = ai.get('phone') or final_phone
                    method = "ai_assisted"
                else: continue

            # ШАГ 3: Запись в rposts (Адрес теперь не блокирует!)
            try:
                supabase.table("rposts").insert({
                    "channel_id": ch['channel_id'],
                    "post_text": reg['clean_text'][:1000],
                    "price": final_price,
                    "address": final_address or f"{city} (в тексте)",
                    "phone": final_phone or "Не указан",
                    "raw_json": {"method": method}
                }).execute()
                print(f"   ✅ #{msg.id} [{method}]: {final_price} р. | {final_address}")
            except: continue

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
