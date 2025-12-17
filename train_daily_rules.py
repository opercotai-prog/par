import os
import asyncio
import json
import re
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- ⚙️ НАСТРОЙКИ ---
TARGET_CHANNEL = 'arendakvartirkalingrad' 
POSTS_TO_FETCH = 20 
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
    print(f"⛔️ ОШИБКА: Не найден секрет: {e}")
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 1. СБОР ПОСТОВ ---
async def fetch_raw_posts():
    print(f"📦 Скачиваю последние {POSTS_TO_FETCH} постов из {TARGET_CHANNEL}...")
    
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    
    raw_posts = []
    
    try:
        async for msg in client.iter_messages(TARGET_CHANNEL, limit=POSTS_TO_FETCH):
            if msg.text and len(msg.text) > 30:
                clean_text = msg.text.replace('\n', ' ').strip()
                raw_posts.append(clean_text)
    except Exception as e:
        print(f"⚠️ Ошибка Телеграм: {e}")
    finally:
        await client.disconnect()

    print(f"✅ Скачано {len(raw_posts)} текстовых сообщений.")
    return raw_posts

# --- 2. АНАЛИЗ ЧЕРЕЗ GEMINI ---
def analyze_with_gemini(raw_posts):
    print("🧠 Отправляю данные в Gemini...")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    posts_blob = "\n\n--- POST START ---\n".join(raw_posts)
    
    # ВНИМАНИЕ: Все скобки JSON ниже удвоены {{ }}, чтобы Python не ругался!
    
    prompt = f"""
    Роль: Старший аналитик данных.
    Задача: Настроить парсер для ПОСУТОЧНОЙ аренды (Daily Rent).

    ДАННЫЕ (Сырые посты из канала):
    {posts_blob}

    ТВОЯ ЗАДАЧА:
    1. Найди среди этих постов те, которые:
       - Предлагают АРЕНДУ (не "куплю").
       - Сдаются ПОСУТОЧНО (сутки, ночь, заселение).
       - Являются КВАРТИРОЙ (не гараж).
       - Содержат ЦЕНУ.
    
    2. Если ты нашел хотя бы {REQUIRED_VALID_COUNT} таких постов, создай JSON-конфигурацию.

    ФОРМАТ ОТВЕТА (ВЕРНИ ТОЛЬКО ВАЛИДНЫЙ JSON):
    {{
      "filters": {{
        "whitelist": ["Список обязательных слов (сутки, заселение...)"],
        "blacklist": ["Список слов для ИСКЛЮЧЕНИЯ (длительно, на год...)"]
      }},
      "extraction": {{
        "price_regex": "Regex для цены за сутки (число). Учти форматы: '2500', '2.500', 'от 2000'.",
        "phone_regex": "Regex для телефона РФ"
      }},
      "rooms_dictionary": {{
        "0": ["список синонимов студии"],
        "1": ["список синонимов 1-к"],
        "2": ["список синонимов 2-к"],
        "3": ["список синонимов 3-к"]
      }}
    }}

    Если данных мало, верни JSON: {{ "error": "not_enough_data" }}
    """

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            print(f"❌ Ошибка API Google ({response.status_code}): {response.text}")
            return None

        try:
            answer = response.json()['candidates'][0]['content']['parts'][0]['text']
            clean_json = re.sub(r'```json|```', '', answer).strip()
            return json.loads(clean_json)
        except Exception as e:
            print(f"❌ Ошибка парсинга JSON: {e}")
            return None

    except Exception as e:
        print(f"❌ Системная ошибка: {e}")
        return None

# --- ГЛАВНАЯ ЛОГИКА ---
async def main():
    print("🚀 Запуск AI-Тренера...")
    
    posts = await fetch_raw_posts()
    if not posts:
        return

    rules = analyze_with_gemini(posts)

    if rules:
        if "error" in rules:
            print(f"\n⚠️ ИИ ответил ошибкой: {rules['error']}")
        else:
            print("\n✨ ИИ успешно сгенерировал стратегию!")
            print(json.dumps(rules, indent=2, ensure_ascii=False))
            
            data = {
                "id": 1, 
                "config": rules, 
                "updated_at": "now()"
            }
            
            try:
                supabase.table('parsing_rules').upsert(data).execute()
                print("\n💾 SUCCESS! Правила сохранены в Supabase.")
            except Exception as e:
                print(f"❌ Ошибка записи в БД: {e}")
    else:
        print("❌ Не удалось получить ответ от ИИ.")

if __name__ == "__main__":
    asyncio.run(main())
