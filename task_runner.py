import os
import re
import hashlib
import asyncio
from datetime import datetime, timezone
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- КЛЮЧИ И НАСТРОЙКИ (Берутся из GitHub Secrets) ---
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_str = os.getenv("TG_SESSION_STRING")
supabase_url = os.getenv("SUPABASEE_URL")
supabase_key = os.getenv("SUPABASEE_KEY")

# Инициализация Supabase
supabase = create_client(supabase_url, supabase_key)

def clean_text_by_passport(text):
    """Очистка текста от мусора на основе паттернов канала"""
    trash_markers = ['Подписывайтесь', 'Подпишись', 'Связь с Админом', 'Наш Чат', '⚡️', '________', '#аренда']
    cleaned = text
    # Убираем жирный шрифт и курсив для корректного поиска маркеров
    cleaned = cleaned.replace('*', '').replace('_', '')
    for marker in trash_markers:
        cleaned = cleaned.split(marker)[0]
    return cleaned.strip()

def get_core_data(text, config):
    """Автоматическое извлечение Ядра данных (Цена, Категория, Телефон, Адрес)"""
    
    # 1. Цена (ищем числа от 5000 до 300000)
    # Предварительно чистим текст от пробелов внутри чисел: "25 000" -> "25000"
    text_processed = re.sub(r'(?<=\d)\s(?=\d)', '', text)
    prices = re.findall(r'\b(\d{4,6})\b', text_processed)
    price = 0
    if prices:
        # Берем первое найденное число (в этом канале цена всегда в начале)
        price = int(prices[0])

    # 2. Категория (ищем по границам слов \b)
    category = "other"
    cat_map = {
        "1-room": [r'\b1к\b', r'\b1-к\b', r'1 комнатная', r'однокомнатная'],
        "2-room": [r'\b2к\b', r'\b2-к\b', r'2 комнатная', r'двухкомнатная'],
        "3-room": [r'\b3к\b', r'\b3-к\b', r'3 комнатная', r'трехкомнатная'],
        "studio": [r'студия', r'квартира-студия'],
        "room": [r'\bкомната\b', r'вобщежитии', r'сдается комната']
    }
    for cat_name, patterns in cat_map.items():
        if any(re.search(p, text, re.IGNORECASE) for p in patterns):
            category = cat_name
            break

    # 3. Телефон (стандартный поиск мобильных РФ)
    phones = re.findall(r'\+?\d{10,12}', text.replace(' ', '').replace('-', ''))
    phone = phones[0] if phones else None

    # 4. Адрес (Логика: 2-я строка текста, где обычно пишут улицу)
    lines = text.split('\n')
    address = "Адрес не найден"
    if len(lines) > 1:
        # Ищем первую строку после заголовка, которая длиннее 5 символов
        potential = [l.strip() for l in lines if len(l.strip()) > 5]
        if len(potential) > 1:
            address = potential[1] # Вторая значимая строка

    return price, category, phone, address

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    # Загружаем конфиг канала из базы
    res = supabase.table("channels").select("*").eq("username", "arendatumen72rus").single().execute()
    if not res.data:
        print("❌ Ошибка: Паспорт канала не найден в Supabase!")
        await client.disconnect()
        return

    ch = res.data
    conf = ch['parser_config']
    
    # НАСТРОЙКА ТЕСТОВОГО ПЕРИОДА (27.01.2026 - 28.01.2026)
    start_date = datetime(2026, 1, 27, tzinfo=timezone.utc)
    end_date = datetime(2026, 1, 29, tzinfo=timezone.utc) # До начала 29-го

    print(f"🤖 ЗАПУСК АВТОМАТА для @{ch['username']}")
    print(f"📅 Период: {start_date} ---> {end_date}")

    count = 0
    # Итерируем сообщения от новых к старым, начиная с конца 28 января
    async for msg in client.iter_messages(ch['username'], offset_date=end_date, limit=200):
        # Если ушли глубже 27 января — стоп
        if msg.date < start_date:
            break
        
        if not msg.text or len(msg.text) < 30:
            continue

        # 1. Фильтр СПАМА (из паспорта)
        spam_markers = conf.get('extraction_rules', {}).get('is_spam_markers', [])
        if any(m.lower() in msg.text.lower() for m in spam_markers):
            continue

        # 2. Очистка текста
        clean_text = clean_text_by_passport(msg.text)

        # 3. Авто-извлечение данных (Ядро)
        price, category, phone, address = get_core_data(clean_text, conf)

        # 4. Проверка валидности (если нет цены — это мусор)
        if price < 5000:
            continue

        # 5. Хеширование и сохранение
        content_hash = hashlib.md5(clean_text.encode()).hexdigest()
        
        post_data = {
            "channel_id": ch['id'],
            "telegram_msg_id": msg.id,
            "deal_type": "rent",
            "category": category,
            "price": price,
            "city": "Тюмень",
            "raw_text_cleaned": clean_text,
            "content_hash": content_hash,
            "details": {
                "address_auto": address,
                "method": "automatic_regex_v2"
            }
        }

        try:
            # Запись в таблицу posts
            ins_res = supabase.table("posts").insert(post_data).execute()
            
            if ins_res.data and phone:
                # Запись в таблицу contacts
                supabase.table("contacts").insert({
                    "post_id": ins_res.data[0]['id'],
                    "phones": [phone],
                    "links": {"url": f"https://t.me/{ch['username']}/{msg.id}"}
                }).execute()
                
            print(f"✅ Обработан пост #{msg.id} ({msg.date.strftime('%d.%m %H:%M')}) | {price} руб | {category}")
            count += 1
            
        except Exception as e:
            if "duplicate key" not in str(e):
                print(f"❌ Ошибка на посте {msg.id}: {e}")

    print(f"🏁 ТЕСТ ЗАВЕРШЕН. Всего добавлено: {count} постов.")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
