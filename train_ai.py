import os
import asyncio
import json
import re
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- НАСТРОЙКИ ---
TARGET_CHANNEL = 'arendakvartirkalingrad' 

# ВАЖНО: Листаем до 500 "сообщений" (фоток), чтобы найти хотя бы 10 текстов
MAX_MESSAGES_TO_CHECK = 500 
REQUIRED_TEXTS = 10 

# --- КЛЮЧИ ---
try:
    API_ID = int(os.environ['TG_API_ID'])
    API_HASH = os.environ['TG_API_HASH']
    SESSION_STRING = os.environ['TG_SESSION_STRING']
    SUPABASE_URL = os.environ['SUPABASE_URL']
    SUPABASE_KEY = os.environ['SUPABASE_KEY']
    GEMINI_KEY = os.environ['GEMINI_KEY']
except:
    print("⛔️ Ошибка: Проверь Secrets в GitHub!")
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 1. СБОРЩИК (ИЩЕТ ТЕКСТЫ СРЕДИ ФОТОК) ---
async def fetch_posts():
    print(f"🚜 Начинаю разгребать {TARGET_CHANNEL}...")
    print(f"   (Буду искать, пока не найду {REQUIRED_TEXTS} текстовых объявлений)")

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    
    clean_posts = []
    
    # Листаем много (500), но берем только нужное
    async for msg in client.iter_messages(TARGET_CHANNEL, limit=MAX_MESSAGES_TO_CHECK):
        
        # Если это текст и он длиннее 30 символов
        if msg.text and len(msg.text) > 30:
            # Убираем лишние пробелы и энтеры
            text = msg.text.replace('\n', ' ').strip()
            clean_posts.append(text)
            print(f"   ✅ Нашел текст #{len(clean_posts)}")
        
        # Если набрали 10 штук — хватит, останавливаемся
        if len(clean_posts) >= REQUIRED_TEXTS:
            print("   ✋ Хватит, набрали норму.")
            break
            
    await client.disconnect()
    
    print(f"📦 ИТОГ: Собрано {len(clean_posts)} постов для ИИ.")
    return clean_posts

# --- 2. МОЗГИ (GEMINI) ---
def ask_gemini(posts):
    if len(posts) < 2:
        print("❌ Слишком мало текстов. Проверь имя канала.")
        return None

    print("🧠 Отправляю в Gemini...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    # Склеиваем посты в одну колбасу
    data_str = "\n--- NEXT POST ---\n".join(posts)

    # Простая строка без фигурных скобок, чтобы питон не тупил
    prompt_intro = """
    Ты аналитик данных. Твоя задача — создать конфигурацию для парсера.
    
    1. Прочитай посты ниже.
    2. Пойми, как в этом канале пишут объявления (какие слова используют для сдачи, как пишут цены).
    3. Создай JSON-правила.
    
    ВЕРНИ ТОЛЬКО JSON ТАКОГО ВИДА:
    {
      "filters": {
        "whitelist": ["массив слов, которые ОБЯЗАТЕЛЬНО должны быть в объявлении (например: сдам, аренда)"],
        "blacklist": ["массив слов, которые запрещены (например: куплю, сниму, ищу)"]
      },
      "regex": {
        "price": "напиши регулярное выражение python, которое вытаскивает цену (число) из текста. Учти форматы из постов.",
        "phone": "регулярное выражение для телефона"
      }
    }
    """
    
    full_prompt = prompt_intro + "\n\nВОТ ПОСТЫ:\n" + data_str

    payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
    
    try:
        r = requests.post(url, json=payload)
        if r.status_code != 200:
            print(f"Ошибка Google API: {r.text}")
            return None
            
        answer = r.json()['candidates'][0]['content']['parts'][0]['text']
        # Чистим ответ от ```json
        clean = re.sub(r'```json|```', '', answer).strip()
        return json.loads(clean)
    except Exception as e:
        print(f"Ошибка обработки ответа: {e}")
        return None

# --- ЗАПУСК ---
async def main():
    # 1. Сбор
    posts = await fetch_posts()
    if not posts: return

    # 2. Анализ
    rules = ask_gemini(posts)
    
    # 3. Сохранение
    if rules:
        print("\n✨ ИИ СГЕНЕРИРОВАЛ ПРАВИЛА:")
        print(json.dumps(rules, indent=2, ensure_ascii=False))
        
        try:
            # Пишем в базу под ID=1
            supabase.table('parsing_rules').upsert({
                "id": 1,
                "config": rules,
                "updated_at": "now()"
            }).execute()
            print("\n💾 УСПЕХ! Данные записаны в таблицу 'parsing_rules'.")
        except Exception as e:
            print(f"\n❌ Ошибка записи в базу: {e}")
            print("Убедись, что таблица parsing_rules существует!")
    else:
        print("ИИ ничего не вернул.")

if __name__ == "__main__":
    asyncio.run(main())
