import os
import asyncio
import json
import re
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- НАСТРОЙКИ ---
TARGET_CHANNEL = 'arendakvartirkalingrad' # Твой канал с посуточной арендой
POSTS_TO_FETCH = 15      # Берем с запасом, чтобы набралось 10 текстовых
REQUIRED_VALID_COUNT = 5 # ИИ должен найти минимум 5 подходящих внутри пачки

try:
    API_ID = int(os.environ['TG_API_ID'])
    API_HASH = os.environ['TG_API_HASH']
    SESSION_STRING = os.environ['TG_SESSION_STRING']
    SUPABASE_URL = os.environ['SUPABASE_URL']
    SUPABASE_KEY = os.environ['SUPABASE_KEY']
    GEMINI_KEY = os.environ['GEMINI_KEY']
except KeyError:
    print("⛔️ Ошибка: Проверь переменные окружения!")
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 1. СБОР СЫРЫХ ДАННЫХ (Python работает как грузчик) ---
async def fetch_raw_posts():
    print(f"📦 Скачиваю последние посты из {TARGET_CHANNEL}...")
    
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    
    raw_posts = []
    
    # Просто берем последние сообщения, игнорируя только пустые картинки
    async for msg in client.iter_messages(TARGET_CHANNEL, limit=POSTS_TO_FETCH):
        if msg.text and len(msg.text) > 30: # Если есть хоть какой-то текст
            # Чистим от лишних энтеров для экономии токенов
            clean_text = msg.text.replace('\n', ' ')
            raw_posts.append(clean_text)
            
        if len(raw_posts) >= 10: # Нам нужно 10 текстовых кусков
            break
            
    await client.disconnect()
    print(f"📦 Скачано {len(raw_posts)} текстовых сообщений. Отправляю в ИИ...")
    return raw_posts

# --- 2. ИНТЕЛЛЕКТУАЛЬНЫЙ АНАЛИЗ (Gemini) ---
def analyze_with_gemini(raw_posts):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    # Склеиваем посты для отправки
    posts_blob = "\n\n--- POST START ---\n".join(raw_posts)
    
    prompt = f"""
    Роль: Главный аналитик данных по недвижимости.
    Задача: Настроить парсер для ПОСУТОЧНОЙ аренды (Daily Rent).

    ДАННЫЕ:
    Ниже список из 10 сырых постов. Среди них могут быть объявления о продаже, долгосрочной аренде или спам.
    {posts_blob}

    ИНСТРУКЦИЯ:
    1. Просканируй эти посты. Найди среди них ТЕ, которые соответствуют критериям:
       - Это сдача в аренду (не "куплю", не "сниму").
       - Это ПОСУТОЧНО (есть слова: сутки, ночь, заселение, свободна, бронь).
       - Это КВАРТИРА или ДОМ (не гараж, не офис).
       - Есть ЦЕНА.
    
    2. Если ты нашел хотя бы {REQUIRED_VALID_COUNT} таких валидных постов:
       Проанализируй их стиль написания и создай JSON-конфиг.

    ТРЕБОВАНИЯ К JSON (ВЕРНИ ТОЛЬКО ЕГО):
    {{
      "filters": {{
        "whitelist": ["Список слов, которые ОБЯЗАТЕЛЬНО должны быть (на основе найденных валидных постов)"],
        "blacklist": ["Список слов из мусорных постов, которые надо исключить (длительно, на год, куплю)"]
      }},
      "regex_patterns": {{
        "price": "Напиши Regex, который идеально ловит цену в валидных постах. Учти, что посуточная цена (1500-10000) ниже месячной.",
        "phone": "Regex для телефона"
      }},
      "rooms_keywords": {{
        "0": ["синонимы студии"],
        "1": ["синонимы 1к"],
        "2": ["синонимы 2к"]
      }}
    }}

    ЕСЛИ ВАЛИДНЫХ ПОСТОВ МЕНЬШЕ {REQUIRED_VALID_COUNT}, ВЕРНИ JSON: {{"error": "not_enough_data"}}
    """

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            print(f"❌ Ошибка API: {response.status_code}")
            return None

        # Парсим ответ
        answer = response.json()['candidates'][0]['content']['parts'][0]['text']
        clean_json = re.sub(r'```json|```', '', answer).strip()
        return json.loads(clean_json)

    except Exception as e:
        print(f"❌ Ошибка обработки ИИ: {e}")
        return None

# --- ЗАПУСК ---
async def main():
    # 1. Сбор
    posts = await fetch_raw_posts()
    if not posts:
        print("Посты не найдены.")
        return

    # 2. Анализ
    rules = analyze_with_gemini(posts)

    # 3. Результат
    if rules:
        if "error" in rules:
            print(f"\n⚠️ ИИ сказал: {rules['error']}")
            print("Видимо, в последних 10 постах слишком много мусора или долгосрока.")
        else:
            print("\n✨ ИИ успешно создал правила для ПОСУТОЧНОЙ аренды:")
            print(json.dumps(rules, indent=2, ensure_ascii=False))
            
            # Сохраняем в Supabase (id=1, перезаписываем старые)
            data = {"id": 1, "config": rules, "updated_at": "now()"}
            try:
                supabase.table('parsing_rules').upsert(data).execute()
                print("\n💾 Правила сохранены! Можно запускать fast_parser.py")
            except Exception as e:
                print(f"Ошибка БД: {e}")
    else:
        print("Не удалось получить ответ от ИИ.")

if __name__ == "__main__":
    asyncio.run(main())
