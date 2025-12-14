import os
import asyncio
import json
import re
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- НАСТРОЙКИ ---
# Канал-донор, на котором мы будем учить систему (самый качественный)
TARGET_CHANNEL = 'arendakvartirkalingrad' 

try:
    API_ID = int(os.environ['TG_API_ID'])
    API_HASH = os.environ['TG_API_HASH']
    SESSION_STRING = os.environ['TG_SESSION_STRING']
    SUPABASE_URL = os.environ['SUPABASE_URL']
    SUPABASE_KEY = os.environ['SUPABASE_KEY']
    GEMINI_KEY = os.environ['GEMINI_KEY']
except KeyError:
    print("⛔️ Ошибка: Проверь ключи (Secrets) в GitHub или .env")
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- ФУНКЦИЯ ОБЩЕНИЯ С GEMINI ---
def ask_gemini_to_create_rules(raw_posts_text):
    print("🧠 Отправляю данные в Gemini для анализа...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    prompt = f"""
    Роль: Главный разработчик парсера.
    Задача: Проанализируй реальные объявления из Telegram-канала и создай конфигурацию (JSON) для их парсинга.

    ВОТ СЫРЫЕ ПОСТЫ (HISTORY):
    {raw_posts_text}

    ТРЕБОВАНИЯ К JSON:
    1. "semantic_rules":
       - "blacklist_phrases": слова-маркеры спама (куплю, канал, подпишись).
       - "whitelist_phrases": слова-маркеры аренды (сдам, сутки, цена).
       - "city_markers": Найди все города в текстах и их синонимы. Пример: {{"Зеленоградск": ["зелик", "зеленоградск"]}}.
       - "rooms_dictionary": Синонимы комнат (студия=0, 1к=1...).
    2. "regex_patterns":
       - "price": Напиши Python Regex, который вытащит цену из этих конкретных постов (обрати внимание на форматы типа '_З', 'руб', 'к').
       - "phone": Regex для телефона.

    Верни ТОЛЬКО валидный JSON.
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, json=payload)
        result = response.json()
        raw_answer = result['candidates'][0]['content']['parts'][0]['text']
        clean_json = re.sub(r'```json|```', '', raw_answer).strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"❌ Ошибка Gemini: {e}")
        return None

# --- ГЛАВНАЯ ЛОГИКА ---
async def main():
    print(f"🚀 Запуск Авто-Тренера. Цель: {TARGET_CHANNEL}")
    
    # 1. Скачиваем посты через Telethon
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    
    print("📥 Скачиваю историю сообщений...")
    posts_history = []
    
    try:
        entity = await client.get_entity(TARGET_CHANNEL)
        # Берем 30 последних постов - этого достаточно для обучения
        async for msg in client.iter_messages(entity, limit=10):
            if msg.text and len(msg.text) > 50:
                posts_history.append(msg.text)
    except Exception as e:
        print(f"❌ Не удалось прочитать канал: {e}")
        await client.disconnect()
        return

    await client.disconnect()
    
    if not posts_history:
        print("⚠️ Посты не найдены. Канал пустой или закрытый.")
        return

    print(f"✅ Скачано {len(posts_history)} постов. Готовлю данные...")
    full_text_blob = "\n---NEXT POST---\n".join(posts_history)

    # 2. Генерируем JSON
    rules_json = ask_gemini_to_create_rules(full_text_blob)

    if rules_json:
        print("\n💡 JSON СГЕНЕРИРОВАН:")
        print(json.dumps(rules_json, indent=2, ensure_ascii=False))
        
        # 3. Сохраняем в Базу
        data = {
            "id": 1, 
            "config": rules_json,
            "updated_at": "now()"
        }
        supabase.table('parsing_rules').upsert(data).execute()
        print("\n🎉 УСПЕХ! Правила сохранены в базу. Парсер готов к работе.")
    else:
        print("\n❌ Gemini не смог создать JSON.")

if __name__ == '__main__':
    asyncio.run(main())
