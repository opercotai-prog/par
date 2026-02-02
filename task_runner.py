import os
import re
import asyncio
import json
import requests
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- КЛЮЧИ (os.environ.get для GitHub Actions) ---
api_id = int(os.environ.get("TG_API_ID", 0))
api_hash = os.environ.get("TG_API_HASH", "")
session_str = os.environ.get("TG_SESSION_STRING", "")
supabase_url = os.environ.get("SUPABASEE_URL", "")
supabase_key = os.environ.get("SUPABASEE_KEY", "")
gemini_key = os.environ.get("GEMINI_KEY", "")

supabase = create_client(supabase_url, supabase_key)

def analyze_with_ai(text, city):
    """ИИ-Агент: Включается, когда Regex не нашел цену или адрес"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    
    prompt = f"""
    Ты аналитик аренды жилья в г. {city}. Извлеки данные из текста объявления.
    - is_offer: true только если это сдача квартиры (не поиск, не реклама).
    - price: только цифры (основная цена аренды в месяц, не залог).
    - address: только улица и дом или ЖК (без лишнего описания).
    - phone: формат 79XXXXXXXXX.
    
    Текст: {text}
    Верни СТРОГИЙ JSON: {{"price": int, "address": "str", "phone": "str", "is_offer": bool}}
    """
    
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
    """Regex-фильтр: находит 90% постов сам"""
    # 0. Очистка от футера и мусора
    clean_text = text.split('⚡️')[0].split('Подпишись')[0].strip()
    lines = [l.strip() for l in clean_text.split('\n') if len(l.strip()) > 3]
    text_low = clean_text.lower()
    
    # 1. ЯДРО: Ключи аренды
    rent_keywords = ['сдам', 'аренда', 'собственник', 'сдается', 'сдаётся', 'хозяин', 'длительный']
    is_rent = any(word in text_low for word in rent_keywords)
    if not is_rent: return {"is_rent": False}

    # 2. ТЕЛЕФОН: ищем отдельно стоящие 10-11 цифр (избегаем слипания с ценой)
    phone_match = re.search(r'(?:\+?7|8)?[\s\-]?\(?9\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}', clean_text)
    phone = re.sub(r'[^\d]', '', phone_match.group(0)) if phone_match else None
    if phone and len(phone) == 10: phone = "7" + phone
    elif phone and len(phone) == 11 and phone.startswith('8'): phone = "7" + phone[1:]

    # 3. ЦЕНА: ищем число + маркер
    price = 0
    price_pattern = r'(\d[\d\s\.]*)\s*(?:тыс|т\.р|тр|руб|₽|р\.|\s\+|\sкв|в месяц)'
    for m in re.finditer(price_pattern, clean_text, re.IGNORECASE):
        val_str = re.sub(r'[\s\.]', '', m.group(1))
        if not val_str: continue
        val = int(val_str)
        if 10 <= val <= 350: val *= 1000 # из 25 в 25000
        if 5000 <= val <= 350000:
            # Проверка, что это не залог
            if 'залог' not in clean_text[max(0, m.start()-20):m.start()].lower():
                price = val; break

    # 4. АДРЕС: Очистка от мусора (животные, мебель и т.д.)
    address = None
    garbage = ['без животных', 'ранее никто', 'имеется всё', 'собственник', 'сдам', 'показы', 'оплата', 'залог', 'евродвушка']
    addr_markers = ['ул.', 'ул ', 'улица', 'пр.', 'жк', 'мкр', 'тракт', 'адресу', 'д. ', 'корп']
    
    for line in lines:
        line_low = line.lower()
        if any(m in line_low for m in addr_markers):
            if not any(g in line_low for g in garbage):
                address = line[:100].strip(); break
    
    # Если адрес не найден по маркерам - пробуем взять 2-ю или 3-ю строку
    if not address and len(lines) > 1:
        for i in range(1, min(4, len(lines))):
            if not any(g in lines[i].lower() for g in garbage + rent_keywords):
                address = lines[i][:100].strip(); break

    return {
        "is_rent": is_rent, 
        "phone": phone, 
        "price": price, 
        "address": address, 
        "clean_text": clean_text
    }

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    # 1. Берем каналы из базы
    res = supabase.table("channels_passport").select("*").eq("status", "active").execute()
    
    for ch in res.data:
        city = ch.get('city', 'Тюмень')
        print(f"📡 Канал: {ch['channel_id']}")
        
        # Берем посты за последние 2 суток (48 часов)
        async for msg in client.iter_messages(ch['channel_id'].replace('@',''), limit=100):
            if not msg.text or msg.date < (datetime.now(timezone.utc) - timedelta(days=2)): 
                continue

            # ШАГ 1: Попытка Regex
            reg = parse_with_regex(msg.text)
            if not reg.get('is_rent'): continue 

            final_price = reg['price']
            final_address = reg['address']
            final_phone = reg['phone']
            method = "regex"

            # ШАГ 2: ИИ только если Regex не нашел цену или адрес
            if final_price == 0 or not final_address:
                print(f"   🔍 #{msg.id}: Данные неполные (Цена:{final_price}, Адр:{final_address}). Зовем ИИ...")
                ai = analyze_with_ai(reg['clean_text'], city)
                if ai and ai.get('is_offer'):
                    final_price = ai.get('price') or final_price
                    final_address = ai.get('address') or final_address
                    final_phone = ai.get('phone') or final_phone
                    method = "ai_assisted"
                elif final_price == 0: 
                    continue # Если даже ИИ не нашел цену - в мусор

            # ШАГ 3: Запись в rposts
            try:
                supabase.table("rposts").insert({
                    "channel_id": ch['channel_id'],
                    "post_text": reg['clean_text'][:1000],
                    "price": final_price,
                    "address": final_address or f"{city} (см. текст)",
                    "phone": final_phone or "Не указан",
                    "raw_json": {"method": method}
                }).execute()
                print(f"   ✅ #{msg.id} [{method}]: {final_price} р. | {final_address}")
            except:
                continue # Обычно это дубликат

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
