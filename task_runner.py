import os
import re
import asyncio
import json
import requests
import hashlib
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- КЛЮЧИ (СИНХРОНИЗИРОВАНО С ВАШИМИ SECRET) ---
API_ID = os.environ.get('TG_API_ID')
API_HASH = os.environ.get('TG_API_HASH')
SESSION_STRING = os.environ.get('TG_SESSION_STRING')
GEMINI_KEY = os.environ.get('GEMINI_KEY')
SUPABASE_URL = os.environ.get('SUPABASEE_URL') # С опечаткой как в GitHub
SUPABASE_KEY = os.environ.get('SUPABASEE_KEY')

# Инициализация Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

async def analyze_with_ai(text, city):
    """ИИ-Агент: извлекает данные, если Regex не справился"""
    if not GEMINI_KEY:
        print("   ❌ Ошибка: GEMINI_KEY не найден в Environment")
        return None
        
    await asyncio.sleep(2) # Небольшая пауза для лимитов
    
    # ИСПОЛЬЗУЕМ ВЕРХНИЙ РЕГИСТР GEMINI_KEY И РАБОЧУЮ МОДЕЛЬ 1.5
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    prompt = (
        f"Ты аналитик аренды недвижимости в городе {city}. "
        f"Твоя задача извлечь данные из объявления в формате JSON. "
        f"Если это не объявление о сдаче в аренду, поставь is_offer: false. "
        f"Формат: {{'price': int, 'address': str, 'phone': str, 'is_offer': bool}}. "
        f"Текст: {text}"
    )
    
    try:
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        resp = requests.post(url, json=payload, timeout=20)
        res_json = resp.json()
        
        if 'candidates' not in res_json:
            print(f"   ⚠️ Ошибка Gemini API: {res_json.get('error', 'Unknown error')}")
            return None
            
        raw_text = res_json['candidates'][0]['content']['parts'][0]['text']
        # Ищем JSON в ответе ИИ
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return None
    except Exception as e:
        print(f"   ⚠️ Ошибка при запросе к ИИ: {e}")
        return None

def parse_with_regex(text):
    """Быстрый поиск данных через регулярные выражения"""
    # Очистка текста от лишних ссылок и подписей
    clean_text = text.split('⚡️')[0].split('Подпишись')[0].strip()
    text_low = clean_text.lower()
    
    # 1. Проверка на ключевые слова
    rent_keywords = ['сдам', 'аренда', 'собственник', 'сдается', 'студия', 'комната', 'хозяин', 'квартира']
    is_rent = any(word in text_low for word in rent_keywords)

    # 2. Поиск телефона
    digits = re.sub(r'[^\d]', '', clean_text)
    phone_match = re.search(r'(7|8)?9\d{9}', digits)
    phone = phone_match.group(0) if phone_match else None

    # 3. Поиск цены
    price = 0
    price_pattern = r'(\d[\d\s\.]*)\s*(?:тыс|т\.р|тр|руб|₽|р\.|\s\+|\sкв|в месяц)'
    for m in re.finditer(price_pattern, clean_text, re.IGNORECASE):
        # Защита от "кв.м" и "этаж"
        context_after = clean_text[m.end():m.end()+12].lower()
        if any(x in context_after for x in ['кв', ' м', 'эт']): continue
        
        val_str = re.sub(r'[\s\.]', '', m.group(1))
        try:
            val = int(val_str)
            if val <= 350: val *= 1000 # если написано "25", превращаем в 25000
            if 5000 <= val <= 500000:
                # Если перед числом нет слова "залог"
                if 'залог' not in clean_text[max(0, m.start()-20):m.start()].lower():
                    price = val
                    break
        except: continue

    # 4. Поиск адреса (упрощенно)
    address = None
    for line in clean_text.split('\n'):
        if any(m in line.lower() for m in ['ул.', 'улица', 'жк', 'мкр', 'пр.', 'адрес']):
            if not any(p in line.lower() for p in ['руб', 'тыс', '₽']):
                address = line.strip()[:100]
                break
    
    return {"is_rent": is_rent, "phone": phone, "price": price, "address": address, "clean_text": clean_text}

async def run_task():
    print("🚀 Запуск парсера...")
    
    if not all([API_ID, API_HASH, SESSION_STRING]):
        print("❌ Ошибка: Нет данных для авторизации в Telegram!")
        return

    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
    
    try:
        await client.start()
        print("✅ Авторизация в Telegram успешна")

        # Получаем список активных каналов из Supabase
        res_ch = supabase.table("channels_passport").select("*").eq("status", "active").execute()
        
        for ch in res_ch.data:
            city = ch.get('city', 'Тюмень')
            channel_id = ch['channel_id'].replace('@', '')
            print(f"📡 Сбор из: @{channel_id} ({city})")
            
            async for msg in client.iter_messages(channel_id, limit=30):
                # Пропускаем пустые или старые посты (старше 2 дней)
                if not msg.text or msg.date < (datetime.now(timezone.utc) - timedelta(days=2)): 
                    continue

                # 1. Сначала пробуем Regex (бесплатно и быстро)
                reg = parse_with_regex(msg.text)
                if not reg['is_rent']: 
                    continue 

                final_data = reg
                method = "regex"

                # 2. Если Regex не нашел цену или адрес — вызываем ИИ
                if reg['price'] == 0 or not reg['address']:
                    print(f"   🔍 #{msg.id}: Regex не нашел всех данных. Зовем ИИ...")
                    ai_result = await analyze_with_ai(reg['clean_text'], city)
                    
                    if ai_result and ai_result.get('is_offer'):
                        final_data = ai_result
                        method = "ai_assisted"
                    elif reg['price'] > 0:
                        method = "regex_partial"
                    else:
                        continue # Не аренда или данных совсем нет

                # 3. Сохранение в базу данных
                try:
                    content_hash = hashlib.md5(reg['clean_text'].encode()).hexdigest()
                    
                    supabase.table("rposts").insert({
                        "channel_id": ch['channel_id'],
                        "post_text": reg['clean_text'][:1000],
                        "price": final_data.get('price', 0),
                        "address": final_data.get('address') or f"г. {city}",
                        "phone": final_data.get('phone') or "Не указан",
                        "raw_json": {"method": method, "hash": content_hash}
                    }).execute()
                    
                    print(f"   ✅ Пост #{msg.id} сохранен ({method})")
                except Exception as e:
                    # Скорее всего дубликат по хешу, если настроена уникальность в БД
                    continue

    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
    finally:
        await client.disconnect()
        print("job finished")

if __name__ == "__main__":
    asyncio.run(run_task())
