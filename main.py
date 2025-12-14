import os
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client
import requests

# --- ЗАГРУЗКА КЛЮЧЕЙ ---
try:
    API_ID = int(os.environ['TG_API_ID'])
    API_HASH = os.environ['TG_API_HASH']
    SESSION_STRING = os.environ['TG_SESSION_STRING']
    SUPABASE_URL = os.environ['SUPABASE_URL']
    SUPABASE_KEY = os.environ['SUPABASE_KEY']
    GEMINI_KEY = os.environ['GEMINI_KEY']
except KeyError:
    print("❌ Ошибка: Не найдены секреты в GitHub!")
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Карта каналов (пока простая, потом можно тоже брать из БД)
CHANNELS_MAP = {
    'arendakvartirkalingrad': 'Калининград',
    #'arendakvartirkalingrad': 'Калининград'
}

def get_ai_rules():
    """Скачивает 'Мозги' (JSON) из базы данных"""
    try:
        # Берем запись с ID=1 (куда пишет train_ai.py)
        response = supabase.table('parsing_rules').select('config').eq('id', 1).execute()
        if response.data:
            print("🧠 Правила (JSON) успешно загружены из базы!")
            return response.data[0]['config']
    except Exception as e:
        print(f"⚠️ Ошибка загрузки правил: {e}")
    
    print("⚠️ Работаем на дефолтных настройках (без фильтров)")
    return {}

def analyze_with_gemini_fallback(text, city):
    """Платный/Медленный способ - только для сложных случаев"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
    prompt = f"""
    JSON данные из текста:
    Текст: {text}
    Город: {city}
    Верни JSON: {{address, price(int), rooms(str), contact_phone, is_agent(bool)}}
    """
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        resp = requests.post(url, json=payload).json()
        clean = re.sub(r'```json|```', '', resp['candidates'][0]['content']['parts'][0]['text']).strip()
        return json.loads(clean)
    except:
        return None

async def main():
    print("🚀 Запуск Умного Парсера...")
    
    # 1. ЗАГРУЖАЕМ ПАМЯТЬ МАШИНЫ
    RULES = get_ai_rules()
    
    # Подготовка списков из правил
    blacklist = [w.lower() for w in RULES.get('semantic_rules', {}).get('blacklist_phrases', [])]
    whitelist = [w.lower() for w in RULES.get('semantic_rules', {}).get('whitelist_phrases', [])]
    
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()

    cutoff_date = datetime.now(timezone.utc) - timedelta(hours=24)

    for channel, default_city in CHANNELS_MAP.items():
        print(f"\n📺 Читаем канал: {channel}")
        try:
            entity = await client.get_entity(channel)
        except:
            print(f"   ❌ Канал недоступен")
            continue

        async for msg in client.iter_messages(entity, limit=20):
            if not msg.text or msg.date < cutoff_date:
                continue

            # --- ЭТАП 1: БЫСТРЫЙ ФИЛЬТР (БЕСПЛАТНО) ---
            text_lower = msg.text.lower()
            
            # Проверка на дубли
            exists = supabase.table('ads').select('id').eq('external_id', str(msg.id)).execute()
            if exists.data:
                continue

            # Фильтр МУСОРА (используем память AI)
            if blacklist and any(bad in text_lower for bad in blacklist):
                print(f"   🗑 Мусор (Blacklist): {msg.id}")
                # Можно сохранять в лог rejected, если хочешь
                continue
            
            # Если нет ключевых слов КВАРТИРЫ - тоже пропускаем (экономим AI)
            if whitelist and not any(good in text_lower for good in whitelist):
                print(f"   ⏩ Пропуск (нет ключевых слов): {msg.id}")
                continue

            # --- ЭТАП 2: ИЗВЛЕЧЕНИЕ ДАННЫХ ---
            print(f"   💎 Найден кандидат: {msg.id}")
            
            # ТУТ мы можем попробовать Regular Expressions из RULES
            # Но пока для надежности отдадим финал в Gemini (или используем гибрид)
            data = analyze_with_gemini_fallback(msg.text, default_city)
            
            if data:
                record = {
                    'source_url': channel,
                    'external_id': str(msg.id),
                    'raw_text': msg.text,  # <--- СОХРАНЯЕМ ПАМЯТЬ!
                    'city': data.get('city', default_city),
                    'address': data.get('address'),
                    'price': data.get('price'),
                    'rooms': str(data.get('rooms')),
                    'is_agent': data.get('is_agent', False),
                    'status': 'new',
                    'created_at': datetime.now().isoformat()
                }
                try:
                    supabase.table('ads').insert(record).execute()
                    print(f"      ✅ Сохранено в базу!")
                except Exception as e:
                    print(f"      ❌ Ошибка записи: {e}")

    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
