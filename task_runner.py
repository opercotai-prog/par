import os, re, hashlib, asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# Настройки
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_str = os.getenv("TG_SESSION_STRING")
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

supabase = create_client(supabase_url, supabase_key)

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    # 1. Берем канал и его конфиг
    res = supabase.table("channels").select("*").eq("username", "arendatumen72rus").single().execute()
    ch = res.data
    conf = ch['parser_config']
    
    # 2. Идем в Телеграм за новыми постами
    # offset_id - это с какого сообщения начинать (берем наш last_message_id)
    new_last_id = ch['last_message_id']
    
    async for msg in client.iter_messages(ch['username'], min_id=ch['last_message_id'], reverse=True):
        if not msg.text: continue
        
        # 3. СОРТИРОВКА (Логика Шага 2)
        # Очистка по маркеру
        clean_text = msg.text.split(conf['code_instructions']['trash_marker'])[0].strip()
        
        # Поиск цены (простая регулярка: ищем цифры перед ₽ или руб)
        price_search = re.findall(r'(\d[\d\s]{2,})\s*(?:₽|руб)', clean_text.replace('\xa0', ' '))
        price = int(re.sub(r'\s+', '', price_search[0])) if price_search else 0
        
        # Определение категории по маппингу
        category = "other"
        for key, value in conf['code_instructions']['category_map'].items():
            if key.lower() in clean_text.lower():
                category = value
                break
        
        # Хеш для защиты от дублей
        content_hash = hashlib.md5(clean_text.encode()).hexdigest()

        # 4. ЗАПИСЬ В SUPABASE
        post_data = {
            "channel_id": ch['id'],
            "telegram_msg_id": msg.id,
            "deal_type": "rent",
            "category": category,
            "price": price,
            "city": conf['typing']['geo_city'],
            "raw_text_cleaned": clean_text,
            "content_hash": content_hash,
            "details": {"raw_full_text": msg.text} # сохраняем оригинал на всякий
        }

        # Вставляем пост
        try:
            ins_res = supabase.table("posts").insert(post_data).execute()
            if ins_res.data:
                # Если пост вставился, вытаскиваем контакты (Шаг 3)
                phones = re.findall(r'\+?\d{10,12}', clean_text)
                handles = re.findall(r'@\w+', clean_text)
                supabase.table("contacts").insert({
                    "post_id": ins_res.data[0]['id'],
                    "phones": phones,
                    "tg_handles": handles
                }).execute()
        except Exception as e:
            print(f"Ошибка (возможно дубль): {e}")

        # Обновляем максимальный ID
        if msg.id > new_last_id:
            new_last_id = msg.id

    # 5. Сохраняем прогресс (последний ID) в базу
    supabase.table("channels").update({"last_message_id": new_last_id}).eq("id", ch['id']).execute()
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
