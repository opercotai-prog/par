import os
import asyncio
import json
import re
import requests
from datetime import datetime, timezone
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- НАСТРОЙКИ ---
TARGET_CHANNEL = 'arendakvartirkalingrad' 

try:
    API_ID = int(os.environ['TG_API_ID'])
    API_HASH = os.environ['TG_API_HASH']
    SESSION_STRING = os.environ['TG_SESSION_STRING']
    SUPABASE_URL = os.environ['SUPABASE_URL']
    SUPABASE_KEY = os.environ['SUPABASE_KEY']
    GEMINI_KEY = os.environ['GEMINI_KEY']
except KeyError:
    print("⛔️ Ошибка: Проверь ключи (Secrets)")
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- ФУНКЦИЯ GEMINI (Та же самая) ---
def ask_gemini_to_create_rules(raw_posts_text):
    print(f"🧠 Анализирую {len(raw_posts_text)} символов текста...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
    
    prompt = f"""
    Роль: Разработчик парсера.
    Задача: Проанализируй объявления за 13-14 декабря и создай JSON-правила.

    ВОТ ПОСТЫ (HISTORY):
    {raw_posts_text}

    ТРЕБОВАНИЯ К JSON:
    1. "semantic_rules": {{
       "blacklist_phrases": ["список стоп-слов"],
       "whitelist_phrases": ["список слов аренды"],
       "city_markers": {{ "Город": ["синоним"] }},
       "rooms_dictionary": {{ "0": ["студия"] }}
    }}
    2. "regex_patterns": {{
       "price": "Regex для цены (учти '_З' и другие форматы)",
       "phone": "Regex для телефона"
    }}

    Верни ТОЛЬКО JSON.
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, json=payload)
        clean_json = re.sub(r'```json|```', '', response.json()['candidates'][0]['content']['parts'][0]['text']).strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"❌ Ошибка Gemini: {e}")
        return None

# --- ГЛАВНАЯ ЛОГИКА ---
async def main():
    print(f"🚀 Запуск Тренера по датам (13-14.12.2025). Канал: {TARGET_CHANNEL}")
    
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    
    posts_history = []
    
    # 1. ЗАДАЕМ ВРЕМЕННЫЕ РАМКИ (UTC)
    # С 00:00 13 декабря до 23:59 14 декабря 2025 года
    start_date = datetime(2025, 12, 13, 0, 0, 0, tzinfo=timezone.utc)
    end_date = datetime(2025, 12, 14, 23, 59, 59, tzinfo=timezone.utc)
    
    print(f"📅 Ищем посты в интервале:\n   От: {start_date}\n   До: {end_date}")
    
    try:
        entity = await client.get_entity(TARGET_CHANNEL)
        
        # Листаем без лимита по количеству, тормозим по дате
        async for msg in client.iter_messages(entity):
            
            # Если сообщение БУДУЩЕЕ (вдруг часы сбиты), пропускаем
            if msg.date > end_date:
                continue
                
            # Если сообщение СТАРШЕ 13 декабря -> СТОП МАШИНА
            if msg.date < start_date:
                print(f"🛑 Наткнулся на старый пост от {msg.date.strftime('%d.%m %H:%M')}. Остановка.")
                break
            
            # Если мы тут, значит дата подходит (13 или 14 число)
            # Фильтруем текст
            if msg.text and len(msg.text) > 50:
                print(f"   ✅ Взят пост от {msg.date.strftime('%d.%m %H:%M')}: {msg.text[:40]}...")
                # Чистим текст
                clean_text = msg.text.replace('\n', ' ')
                posts_history.append(clean_text)
            else:
                print(f"   🗑 Пропущен (короткий/картинка) от {msg.date.strftime('%d.%m %H:%M')}")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        await client.disconnect()
        return

    await client.disconnect()
    
    print(f"\n📊 Итого собрано: {len(posts_history)} постов за 13-14 число.")

    if not posts_history:
        print("⚠️ За эти даты постов не найдено.")
        return

    full_text_blob = "\n---NEXT POST---\n".join(posts_history)

    # 2. Генерируем JSON
    rules_json = ask_gemini_to_create_rules(full_text_blob)

    if rules_json:
        print("\n💡 JSON СГЕНЕРИРОВАН:")
        print(json.dumps(rules_json, indent=2, ensure_ascii=False))
        
        data = {
            "id": 1, 
            "config": rules_json,
            "updated_at": "now()"
        }
        supabase.table('parsing_rules').upsert(data).execute()
        print("\n🎉 УСПЕХ! Правила сохранены.")
    else:
        print("\n❌ Ошибка генерации.")

if __name__ == '__main__':
    asyncio.run(main())
