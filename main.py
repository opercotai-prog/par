import os
import asyncio
import json
import re
import requests
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- 1. НАСТРОЙКИ И КЛЮЧИ ---
try:
    API_ID = int(os.environ['TG_API_ID'])
    API_HASH = os.environ['TG_API_HASH']
    SESSION_STRING = os.environ['TG_SESSION_STRING']
    SUPABASE_URL = os.environ['SUPABASE_URL']
    SUPABASE_KEY = os.environ['SUPABASE_KEY']
    GEMINI_KEY = os.environ['GEMINI_KEY']
except KeyError as e:
    print(f"⛔️ КРИТИЧЕСКАЯ ОШИБКА: Не найден секрет {e} в GitHub!")
    exit(1)

# Подключение к базе
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Список каналов для мониторинга (ключ - ссылка, значение - город по умолчанию)
# Потом этот список можно тоже перенести в базу данных
CHANNELS_MAP = {
    #'kld_arenda': 'Калининград',
    'arendakvartirkalingrad': 'Калининград',
    #'kvartira39': 'Калининград',
    #'avito_kaliningrad': 'Калининград'
}

# --- 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_ai_rules():
    """Скачивает JSON с правилами из базы данных (созданный Тренером)"""
    print("📥 Загрузка правил фильтрации...")
    try:
        # Берем запись с ID=1
        response = supabase.table('parsing_rules').select('config').eq('id', 1).execute()
        if response.data and response.data[0]['config']:
            print("🧠 Правила успешно загружены!")
            return response.data[0]['config']
    except Exception as e:
        print(f"⚠️ Ошибка загрузки правил: {e}")
    
    print("⚠️ Правила не найдены. Работаем без фильтров (все подряд).")
    return {}

def analyze_with_gemini(text, default_city):
    """Отправляет текст в Gemini для извлечения сложной структуры"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    # Промпт настроен на извлечение города и типа аренды
    prompt = f"""
    Роль: Ассистент по недвижимости.
    Задача: Извлеки данные из текста объявления в JSON.
    
    Текст: "{text}"
    Контекст (город по умолчанию): {default_city}
    
    Требования к полям JSON:
    1. city: Если в тексте есть город (Светлогорск, Зеленоградск и т.д.) - пиши его. Если нет - пиши "{default_city}".
    2. address: Улица и дом (строка).
    3. price: Цена (число). Игнорируй залоги.
    4. period: "day" (если посуточно, сутки, ночь) или "month" (если длительно, месяц).
    5. rooms: Количество комнат (строка: "студия", "1", "2", "3").
    6. contact_phone: Номер телефона.
    7. is_agent: true (если комиссия/риелтор), false (если собственник).
    
    Верни ТОЛЬКО чистый JSON.
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            return None
            
        result = response.json()
        raw_text = result['candidates'][0]['content']['parts'][0]['text']
        # Очистка от markdown ```json ... ```
        clean_json = re.sub(r'```json|```', '', raw_text).strip()
        return json.loads(clean_json)
    except Exception:
        return None

# --- 3. ОСНОВНОЙ ЦИКЛ ПАРСЕРА ---

async def main():
    print("🚀 Запуск Умного Парсера...")

    # 1. Получаем "Мозги" (правила)
    rules = get_ai_rules()
    
    # Извлекаем списки из структуры JSON (с защитой от ошибок)
    semantic = rules.get('semantic_rules', {})
    blacklist = [w.lower() for w in semantic.get('blacklist_phrases', [])]
    whitelist = [w.lower() for w in semantic.get('whitelist_phrases', [])]
    
    # 2. Подключаемся к Телеграм
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()

    # Берем посты только за последние 24 часа
    cutoff_date = datetime.now(timezone.utc) - timedelta(hours=24)

    total_added = 0
    total_skipped = 0

    for channel_url, default_city in CHANNELS_MAP.items():
        print(f"\n📺 Канал: {channel_url}")
        try:
            entity = await client.get_entity(channel_url)
        except Exception as e:
            print(f"   ❌ Не могу зайти в канал: {e}")
            continue

        # Читаем последние 20 сообщений
        async for msg in client.iter_messages(entity, limit=20):
            if not msg.text or len(msg.text) < 20 or msg.date < cutoff_date:
                continue

            # --- ПРОВЕРКА ДУБЛЕЙ ---
            # Проверяем, есть ли уже этот ID сообщения в базе
            exists = supabase.table('ads').select('id').eq('external_id', str(msg.id)).eq('source_url', channel_url).execute()
            if exists.data:
                continue # Уже есть, пропускаем молча

            text_lower = msg.text.lower()

            # --- ЭТАП 1: БЫСТРЫЙ ФИЛЬТР (BLACKLIST) ---
            # Если есть стоп-слова (куплю, гараж) - выкидываем сразу
            if blacklist and any(bad_word in text_lower for bad_word in blacklist):
                print(f"   🗑 Skip (Мусор): {msg.id}")
                total_skipped += 1
                continue

            # --- ЭТАП 2: БЫСТРЫЙ ФИЛЬТР (WHITELIST) ---
            # Если нет слов аренды (сдам, квартира) - тоже пропускаем, чтобы не тратить AI
            if whitelist and not any(good_word in text_lower for good_word in whitelist):
                print(f"   ⏩ Skip (Не похоже на квартиру): {msg.id}")
                total_skipped += 1
                continue

            # --- ЭТАП 3: ГЛУБОКИЙ АНАЛИЗ (AI) ---
            print(f"   💎 Обработка кандидата: {msg.id}...")
            data = analyze_with_gemini(msg.text, default_city)

            if data:
                # Формируем запись для базы
                record = {
                    'source_url': channel_url,
                    'external_id': str(msg.id),
                    'raw_text': msg.text,          # Сохраняем оригинал для обучения!
                    'city': data.get('city', default_city),
                    'address': data.get('address'),
                    'price': data.get('price'),
                    'rent_type': data.get('period', 'day'), # day/month
                    'rooms': str(data.get('rooms')),
                    'contact_phone': data.get('contact_phone'),
                    'is_agent': data.get('is_agent', False),
                    'status': 'new',               # Новый статус
                    'ai_analysis': 'Gemini Auto v1',
                    'created_at': datetime.now().isoformat()
                }

                try:
                    supabase.table('ads').insert(record).execute()
                    print(f"      ✅ OK! {data.get('city')}, {data.get('address')}, {data.get('price')} ({data.get('period')})")
                    total_added += 1
                except Exception as e:
                    print(f"      ❌ Ошибка записи в БД: {e}")
            else:
                print("      ⚠️ AI не смог распарсить JSON")

    await client.disconnect()
    print(f"\n🏁 Готово! Добавлено: {total_added}, Пропущено мусора: {total_skipped}")

if __name__ == '__main__':
    asyncio.run(main())
