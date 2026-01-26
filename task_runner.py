import os
import re
import hashlib
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# Используем обновленные названия ключей
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_str = os.getenv("TG_SESSION_STRING")
supabase_url = os.getenv("SUPABASEE_URL")  # Твоя версия с буквой E
supabase_key = os.getenv("SUPABASEE_KEY")  # Твоя версия с буквой E

# Инициализация клиента Supabase
supabase = create_client(supabase_url, supabase_key)

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    # 1. Получаем данные канала и его конфиг (Паспорт)
    # Берем первый активный канал для теста
    res = supabase.table("channels").select("*").eq("username", "arendatumen72rus").single().execute()
    
    if not res.data:
        print("Канал не найден в базе!")
        await client.disconnect()
        return

    ch = res.data
    conf = ch['parser_config']
    last_id = ch.get('last_message_id', 0)
    new_last_id = last_id

    print(f"Начинаем проверку канала {ch['username']} с сообщения #{last_id}")

    # 2. Идем в Телеграм за новыми постами
    # min_id гарантирует, что мы возьмем только посты новее, чем в прошлый раз
    async for msg in client.iter_messages(ch['username'], min_id=last_id, reverse=True):
        if not msg.text:
            continue
        
        # 3. СОРТИРОВКА ПО ПАСПОРТУ
        # Очистка текста от мусора по маркеру из конфига
        trash_marker = conf['code_instructions'].get('trash_marker', "Подписывайтесь")
        clean_text = msg.text.split(trash_marker)[0].strip()
        
        # Поиск цены (цифры перед ₽ или руб)
        price_search = re.findall(r'(\d[\d\s]{2,})\s*(?:₽|руб)', clean_text.replace('\xa0', ' '))
        price = int(re.sub(r'\s+', '', price_search[0])) if price_search else 0
        
        # Определение категории (1к, 2к, студия)
        category = "other"
        for key, value in conf['code_instructions']['category_map'].items():
            if key.lower() in clean_text.lower():
                category = value
                break
        
        # Создаем уникальный хеш текста для защиты от дублей
        content_hash = hashlib.md5(clean_text.encode()).hexdigest()

        # 4. СОХРАНЕНИЕ В БАЗУ
        post_data = {
            "channel_id": ch['id'],
            "telegram_msg_id": msg.id,
            "deal_type": "rent",
            "category": category,
            "price": price,
            "city": conf['typing'].get('geo_city', 'Тюмень'),
            "raw_text_cleaned": clean_text,
            "content_hash": content_hash,
            "details": {"raw_full_text": msg.text}
        }

        try:
            # Вставляем объявление
            ins_res = supabase.table("posts").insert(post_data).execute()
            
            if ins_res.data:
                current_post_id = ins_res.data[0]['id']
                # Вытаскиваем контакты (Шаг 3)
                phones = re.findall(r'\+?\d{10,12}', clean_text)
                handles = re.findall(r'@\w+', clean_text)
                
                supabase.table("contacts").insert({
                    "post_id": current_post_id,
                    "phones": phones,
                    "tg_handles": handles,
                    "links": {"source_msg_id": msg.id}
                }).execute()
                print(f"Добавлен новый пост: #{msg.id}, Цена: {price}")
        
        except Exception as e:
            # Если сработал уникальный индекс на content_hash - это дубль, просто идем дальше
            print(f"Пропуск сообщения {msg.id} (возможно дубль или ошибка): {e}")

        # Запоминаем ID самого последнего сообщения
        if msg.id > new_last_id:
            new_last_id = msg.id

    # 5. Обновляем прогресс канала в базе
    if new_last_id > last_id:
        supabase.table("channels").update({"last_message_id": new_last_id}).eq("id", ch['id']).execute()
        print(f"Прогресс обновлен до #{new_last_id}")
    else:
        print("Новых постов не обнаружено.")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
