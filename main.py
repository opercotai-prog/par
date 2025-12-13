import os
import asyncio
import json
import re
import requests
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- НАСТРОЙКИ КАНАЛОВ (Пока прямо в коде для простоты) ---
CHANNELS_MAP = {
    'arendakvartirkalingrad': 'Калининград',      # Замени на реальные каналы!
    #'avito_kaliningrad': 'Калининград',
    #'dom_kld': 'Калининград'
}

# --- ПОЛУЧЕНИЕ КЛЮЧЕЙ ИЗ GITHUB SECRETS ---
try:
    API_ID = int(os.environ['TG_API_ID'])
    API_HASH = os.environ['TG_API_HASH']
    SESSION_STRING = os.environ['TG_SESSION_STRING']
    GEMINI_KEY = os.environ['GEMINI_KEY']
    SUPABASE_URL = os.environ['SUPABASE_URL']
    SUPABASE_KEY = os.environ['SUPABASE_KEY']
except KeyError as e:
    print(f"⛔️ ОШИБКА: Не найден секретный ключ: {e}")
    print("Убедись, что добавил его в Settings -> Secrets and variables -> Actions")
    exit(1)

# Инициализация Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def analyze_text_gemini(text, city_hint):
    """Отправляем текст в Gemini 2.5"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    prompt = f"""
    Роль: Парсер недвижимости. Город: {city_hint}.
    Текст: "{text}"
    
    Задача: Верни JSON.
    1. address: улица и дом (строка). Если не указано - null.
    2. price: цена (число). Если посуточно - умножь на 30.
    3. rooms: "студия", "1", "2", "3" (строка).
    4. area: площадь (число) или null.
    5. contact_phone: телефон (формат 7XXXXXXXXXX) или null.
    6. is_agent: true (если риелтор/комиссия), false (если собственник).
    
    Ответ ТОЛЬКО JSON. Без markdown.
    """

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            print(f"   ⚠️ Gemini API Error: {response.status_code}")
            return None
        
        result = response.json()
        raw_answer = result['candidates'][0]['content']['parts'][0]['text']
        # Очистка от ```json ... ```
        clean_json = re.sub(r'```json|```', '', raw_answer).strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"   ⚠️ Ошибка парсинга AI: {e}")
        return None

async def main():
    print("🚀 Запуск GitHub Action Parser...")
    
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()

    # Берем посты за последние 24 часа (раз запускаем часто)
    cutoff_date = datetime.now(timezone.utc) - timedelta(hours=24)

    for channel, city in CHANNELS_MAP.items():
        print(f"\n📺 Канал: {channel}")
        try:
            entity = await client.get_entity(channel)
        except:
            print(f"   ❌ Канал {channel} не найден или закрыт.")
            continue

        counter = 0
        # Читаем 20 последних сообщений
        async for msg in client.iter_messages(entity, limit=20):
            if not msg.text or len(msg.text) < 50 or msg.date < cutoff_date:
                continue

            # 1. Проверка на дубли (чтобы не платить за AI зря)
            exists = supabase.table('ads').select('id').eq('source_url', channel).eq('external_id', str(msg.id)).execute()
            if exists.data:
                continue

            print(f"   Processing ID {msg.id}...")
            
            # 2. Анализ через Gemini
            data = analyze_text_gemini(msg.text, city)
            
            if data:
                # 3. Сохранение
                record = {
                    'platform': 'telegram',
                    'source_url': channel,
                    'external_id': str(msg.id),
                    'city': city,
                    'raw_text': msg.text[:1000],
                    'address': data.get('address'),
                    'price': data.get('price'),
                    'rooms': str(data.get('rooms')),
                    'area': data.get('area'),
                    'contact_phone': data.get('contact_phone'),
                    'is_agent': data.get('is_agent', False),
                    'ai_analysis': 'Gemini 1.5 Action',
                    'is_published': True
                }
                try:
                    supabase.table('ads').insert(record).execute()
                    print(f"      ✅ Saved: {data.get('address')} - {data.get('price')}")
                    counter += 1
                except Exception as e:
                    print(f"      ❌ DB Error: {e}")
        
        print(f"   🏁 Добавлено: {counter}")

    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
