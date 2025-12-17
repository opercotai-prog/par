import os
import asyncio
import json
import re
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- ⚙️ НАСТРОЙКИ ---
# Канал, откуда учимся (Посуточная аренда Калининград)
# Убедись, что имя канала правильное!
TARGET_CHANNEL = 'arendakvartirkalingrad' 

# Сколько постов скачивать для анализа
POSTS_TO_FETCH = 20 
# Сколько ИИ должен найти "хороших" объявлений внутри пачки, чтобы создать правила
REQUIRED_VALID_COUNT = 4

# --- 🔑 ПОЛУЧЕНИЕ КЛЮЧЕЙ ---
try:
    API_ID = int(os.environ['TG_API_ID'])
    API_HASH = os.environ['TG_API_HASH']
    SESSION_STRING = os.environ['TG_SESSION_STRING']
    
    SUPABASE_URL = os.environ['SUPABASE_URL']
    SUPABASE_KEY = os.environ['SUPABASE_KEY']
    GEMINI_KEY = os.environ['GEMINI_KEY']
except KeyError as e:
    print(f"⛔️ ОШИБКА: Не найден секретный ключ в GitHub Secrets: {e}")
    print("Проверь настройки репозитория!")
    exit(1)

# Инициализация Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 1. ФУНКЦИЯ СБОРА "СЫРЫХ" ПОСТОВ ---
async def fetch_raw_posts():
    print(f"📦 Скачиваю последние {POSTS_TO_FETCH} постов из {TARGET_CHANNEL}...")
    
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    
    raw_posts = []
    
    try:
        # Листаем сообщения
        async for msg in client.iter_messages(TARGET_CHANNEL, limit=POSTS_TO_FETCH):
            # Берем только те, где есть текст длиннее 30 символов
            # (игнорируем пустые картинки альбомов)
            if msg.text and len(msg.text) > 30:
                # Убираем лишние переносы строк для экономии места
                clean_text = msg.text.replace('\n', ' ').strip()
                raw_posts.append(clean_text)
                
    except Exception as e:
        print(f"⚠️ Ошибка при чтении Telegram: {e}")
    finally:
        await client.disconnect()

    print(f"✅ Скачано {len(raw_posts)} текстовых сообщений.")
    return raw_posts

# --- 2. АНАЛИЗ ЧЕРЕЗ GEMINI (ИСПРАВЛЕНО) ---
def analyze_with_gemini(raw_posts):
    print("🧠 Отправляю данные в Gemini 1.5 Flash...")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    # Склеиваем посты в один текст через разделитель
    posts_blob = "\n\n--- POST START ---\n".join(raw_posts)
    
    # ВНИМАНИЕ: В f-строках ниже фигурные скобки для JSON удвоены {{ }}, 
    # а скобки для переменных оставлены одинарными { }. Это исправляет ValueError.
    
    prompt = f"""
    Роль: Старший аналитик данных (Real Estate Data Engineer).
    Задача: Настроить парсер для ПОСУТОЧНОЙ аренды (Daily Rent).

    ДАННЫЕ:
    Ниже список последних постов из канала. Там может быть мусор, реклама, "куплю", "сниму".
    {posts_blob}

    ТВОЯ ЗАДАЧА:
    1. Просканируй эти посты. Найди среди них ТЕ, которые соответствуют критериям:
       - Это предложение АРЕНДЫ (СДАМ), а не спрос (сниму).
       - Это ПОСУТОЧНО (есть слова: сутки, ночь, заселение, свободна, бронь, даты).
       - Это КВАРТИРА/ДОМ (не гараж, не офис).
       - В тексте есть ЦЕНА (обычно 1000-15000 руб).
    
    2. Если ты нашел хотя бы {REQUIRED_VALID_COUNT} таких постов:
       На их основе создай JSON-конфигурацию.

    ФОРМАТ ОТВЕТА (ВЕРНИ ТОЛЬКО ВАЛИДНЫЙ JSON):
    {{
      "filters": {{
        "whitelist": ["Список слов, которые ОБЯЗАТЕЛЬНО должны быть (например: сутки, заселение, выезд)"],
        "blacklist": ["Список слов для ИСКЛЮЧЕНИЯ (например: длительно, на год, куплю, ищу, сниму)"]
      }},
      "extraction": {{
        "price_regex": "Напиши ОДИН мощный Python Regex, который извлекает число цены за сутки. Учти форматы из постов (например: '2500', '2.500', 'от 2000'). Группа захвата должна брать только цифры.",
        "phone_regex": "Regex для телефона РФ"
      }},
      "rooms_dictionary": {{
        "0": ["список синонимов для студий, если встретились"],
        "1": ["список синонимов для 1-к"],
        "2": ["список синонимов для 2-к"],
        "3": ["список синонимов для 3-к"]
      }}
    }}

    Если валидных постов для анализа мало, верни JSON: {{ "error": "not_enough_data" }}
    """

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            print(f"❌ Ошибка API Google ({response.status_code}): {response.text}")
            return None

        # Парсим ответ
        try:
            answer = response.json()['candidates'][0]['content']['parts'][0]['text']
            # Чистим от ```json и ```
            clean_json = re.sub(r'```json|```', '', answer).strip()
            return json.loads(clean_json)
        except Exception as e:
            print(f"❌ Ошибка парсинга JSON от Gemini: {e}")
            print(f"Ответ был: {response.text[:200]}...") 
            return None

    except Exception as e:
        print(f"❌ Системная ошибка requests: {e}")
        return None

# --- ГЛАВНАЯ ЛОГИКА ---
async def main():
    print("🚀 Запуск AI-Тренера...")
    
    # 1. Скачиваем данные
    posts = await fetch_raw_posts()
    
    if not posts:
        print("⚠️ Не удалось получить посты. Проверь канал или Telegram.")
        return

    # 2. Анализируем через ИИ
    rules = analyze_with_gemini(posts)

    # 3. Сохраняем результат
    if rules:
        if "error" in rules:
            print(f"\n⚠️ ИИ не смог создать правила: {rules['error']}")
            print("Причина: В последних постах мало объявлений о посуточной аренде.")
        else:
            print("\n✨ ИИ успешно сгенерировал стратегию!")
            print(json.dumps(rules, indent=2, ensure_ascii=False))
            
            # Пишем в базу (ID=1)
            data = {
                "id": 1, 
                "config": rules, 
                "updated_at": "now()"
            }
            
            try:
                # Upsert = Обновить или Вставить
                supabase.table('parsing_rules').upsert(data).execute()
                print("\n💾 SUCCESS! Правила сохранены в Supabase.")
                print("Теперь `fast_parser.py` будет работать по этим правилам.")
            except Exception as e:
                print(f"❌ Ошибка записи в базу данных: {e}")
    else:
        print("❌ Не удалось получить ответ от ИИ.")

if __name__ == "__main__":
    asyncio.run(main())
