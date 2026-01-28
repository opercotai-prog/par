import os
import re
import hashlib
import asyncio
import json
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- НАСТРОЙКИ И КЛЮЧИ (GitHub Secrets) ---
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_str = os.getenv("TG_SESSION_STRING")
supabase_url = os.getenv("SUPABASEE_URL")  # С буквой E
supabase_key = os.getenv("SUPABASEE_KEY")  # С буквой E
gemini_key = os.getenv("GEMINI_KEY")

# Инициализация Supabase
supabase = create_client(supabase_url, supabase_key)

# --- ФУНКЦИЯ ИИ (Gemini Flash 1.5) ---
def analyze_with_ai(text, city_hint):
    """Отправляет сложный текст объявления в ИИ для распознавания параметров."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    
    prompt = f"""
    Проанализируй объявление об аренде жилья в городе {city_hint}.
    Текст: "{text}"
    
    Верни ТОЛЬКО JSON объект (без markdown):
    {{
      "price": число_или_null,
      "category": "studio/1-room/2-room/3-room/room/null",
      "address": "улица и номер дома или null",
      "comment": "краткое пояснение"
    }}
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            result = response.json()
            answer = result['candidates'][0]['content']['parts'][0]['text']
            # Чистим ответ от возможных символов ```json
            cleaned = re.sub(r'```json|```', '', answer).strip()
            return json.loads(cleaned)
    except Exception as e:
        print(f"      ⚠️ Ошибка в блоке ИИ: {e}")
    return None

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    # 1. Загружаем паспорт канала
    res = supabase.table("channels").select("*").eq("username", "arendatumen72rus").single().execute()
    if not res.data:
        print("❌ Канал не найден в базе!")
        await client.disconnect()
        return
    
    ch = res.data
    conf = ch['parser_config']
    last_id = ch.get('last_message_id', 0)
    city = conf['typing'].get('geo_city', 'Тюмень')

    print(f"🚀 Запуск проверки @{ch['username']} с сообщения #{last_id}")

    # 2. Получаем новые сообщения
    async for msg in client.iter_messages(ch['username'], min_id=last_id, reverse=True, limit=50):
        if not msg.text or len(msg.text) < 30:
            continue
        
        # --- ПЕРЕМЕННЫЕ ПО УМОЛЧАНИЮ (чтобы не было UnboundLocalError) ---
        ai_analysis = "Processed by Regex"
        category = "other"
        price = 0
        
        # 3. ПЕРВИЧНАЯ ОЧИСТКА ТЕКСТА
        # Отрезаем всё после хештегов или разделителей
        clean_text = msg.text.split('#')[0].split('________')[0].split('[Подпишись')[0].strip()
        
        # 4. ПОПЫТКА ОБРАБОТКИ КОДОМ (Regex)
        # Ищем цену: цифры перед знаком ₽, руб, т.р.
        price_found = re.findall(r'(\d[\d\s]{3,})\s*(?:₽|руб|т\.р|тыс)', clean_text.replace('\xa0', ' '))
        if price_found:
            price = int(re.sub(r'\s+', '', price_found[0]))

        # Ищем категорию по словарю из паспорта
        for key, value in conf['code_instructions']['category_map'].items():
            if key.lower() in clean_text.lower():
                category = value
                break

        # 5. ТРИГГЕР ИИ: Если цена не найдена ИЛИ категория осталась "other"
        if price < 5000 or category == "other":
            print(f"🔍 Пост {msg.id}: Нужна помощь ИИ (Цена: {price}, Кат: {category})")
            ai_data = analyze_with_ai(clean_text, city)
            
            if ai_data:
                price = ai_data.get('price') or price
                category = ai_data.get('category') or category
                ai_analysis = f"AI Success: {ai_data.get('comment', '')}"
            else:
                ai_analysis = "AI failed or returned empty"

        # 6. ФИНАЛЬНАЯ ПРОВЕРКА И ЗАПИСЬ
        if price < 5000 or category == "other":
            print(f"🔍 Пост {msg.id}: Нужна помощь ИИ (Цена: {price}, Кат: {category})")
            ai_data = analyze_with_ai(clean_text, city)
            
            if ai_data:
                # ДОБАВЬ ЭТУ СТРОКУ НИЖЕ:
                print(f"      🤖 Ответ ИИ для {msg.id}: {ai_data}") 
                
                price = ai_data.get('price') or price
                # ... дальше старый код
            # Обновляем прогресс даже при пропуске, чтобы не возвращаться к этому посту
            last_id = msg.id
            continue

        content_hash = hashlib.md5(clean_text.encode()).hexdigest()
        
        post_data = {
            "channel_id": ch['id'],
            "telegram_msg_id": msg.id,
            "deal_type": "rent",
            "category": category,
            "price": price,
            "city": city,
            "raw_text_cleaned": clean_text,
            "content_hash": content_hash,
            "details": {
                "ai_comment": ai_analysis,
                "full_text_raw": msg.text[:1000] # Сохраняем начало оригинала для отладки
            }
        }

        try:
            ins_res = supabase.table("posts").insert(post_data).execute()
            if ins_res.data:
                # Извлекаем контакты
                phones = re.findall(r'\+?\d{10,12}', clean_text)
                supabase.table("contacts").insert({
                    "post_id": ins_res.data[0]['id'],
                    "phones": phones,
                    "links": {"msg_url": f"https://t.me/{ch['username']}/{msg.id}"}
                }).execute()
                print(f"✅ Добавлен: #{msg.id} | {price} руб | {category}")
        except Exception as e:
            if "duplicate key" not in str(e):
                print(f"❌ Ошибка записи #{msg.id}: {e}")
            else:
                print(f"ℹ️ Пост #{msg.id} уже в базе (дубликат).")

        last_id = msg.id

    # 7. ОБНОВЛЯЕМ ПОСЛЕДНИЙ ID В БАЗЕ КАНАЛОВ
    supabase.table("channels").update({"last_message_id": last_id}).eq("id", ch['id']).execute()
    print(f"🏁 Завершено. Последний обработанный ID: {last_id}")
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
