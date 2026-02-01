import os
import re
import asyncio
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- НАСТРОЙКИ (GitHub Secrets) ---
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_str = os.getenv("TG_SESSION_STRING")
supabase_url = os.getenv("SUPABASEE_URL")
supabase_key = os.getenv("SUPABASEE_KEY")

supabase = create_client(supabase_url, supabase_key)

def parse_post_logic(text):
    """
    БИНАРНЫЙ ПАРСЕР С МЕТОДОМ ИСКЛЮЧЕНИЙ
    """
    # 0. Очистка текста
    clean_text = text.split('Подпишись')[0].split('⚡️')[0].split('http')[0].replace('\xa0', ' ').strip()
    lines = [line.strip() for line in clean_text.split('\n') if line.strip()]
    text_low = clean_text.lower()
    
    # --- 1. ЯДРО: БЕРЕМ / НЕ БЕРЕМ (Бинарно по ключам) ---
    rent_markers = ['сдам', 'аренда', 'собственник', 'хозяин', 'сдается', 'сдаётся', 'длительный', 'евродвушка', 'полдома']
    if not any(m in text_low for m in rent_markers):
        return "TRASH", None

    # --- 2. ХВОСТ: ТЕЛЕФОН ---
    digits_only = re.sub(r'[^\d]', '', clean_text)
    phone_match = re.search(r'(7|8)?(9\d{9})', digits_only)
    phone = phone_match.group(0) if phone_match else "Не указан"

    # --- 3. ХВОСТ: ЦЕНА (С ИСКЛЮЧЕНИЯМИ) ---
    price = 0
    # Ищем все группы цифр
    matches = list(re.finditer(r'(\d[\d\s\.]*)', clean_text))
    
    for m in matches:
        val_raw = m.group(1).replace(' ', '').replace('.', '')
        if not val_raw.isdigit() or len(val_raw) < 2: continue
        val = int(val_raw)
        
        start, end = m.span()
        context_before = clean_text[max(0, start-30):start].lower()
        context_after = clean_text[end:end+25].lower()
        full_context = context_before + " [число] " + context_after

        # ИСКЛЮЧАЕМ: Площадь, Этажи, Залоги, Даты, Номера домов
        is_trash = any(word in full_context for word in [
            'кв.м', 'м2', 'м²', 'метр', 'этаж', ' эт', ' год', 
            'залог', 'депозит', 'дом', 'д.', 'корп', 'стр', 'кв.'
        ])
        
        # Если не мусор — ищем маркеры денег рядом
        money_markers = ['тыс', 'тр', 'т.р', 'руб', '₽', 'р.', 'оплата', 'цена', 'стоимость', 'в мес', 'включено']
        if not is_trash and any(mm in full_context for mm in money_markers):
            if val <= 300: val *= 1000 # из "25" в "25000"
            if 5000 <= val <= 400000:
                price = val
                break

    # --- 4. ХВОСТ: АДРЕС (Метод фильтрации строк) ---
    address = "Тюмень"
    addr_anchors = ['ул', 'улица', 'пр.', 'проспект', 'мкр', 'жк', 'тракт', 'квартал', 'пер.', 'проезд', 'подгорная', 'мельникайте', 'федюнинского', 'широтная']
    
    for line in lines:
        line_low = line.lower()
        # Исключаем строки, где явно цена или телефон
        if any(p in line_low for p in ['руб', 'тыс', '₽', 'залог', 'оплата', '+7', '89']): continue
        if len(re.findall(r'\d', line)) > 7: continue 
        
        if any(anchor in line_low for anchor in addr_anchors):
            address = line[:120].strip()
            break
            
    # Если адрес не найден, берем первую строку, которая не "Сдам/Собственник"
    if address == "Тюмень" and len(lines) > 1:
        for i in range(min(4, len(lines))):
            if not any(k in lines[i].lower() for k in ['сдам', 'собственник', 'аренда', 'подпишись']):
                address = lines[i][:120].strip()
                break

    return "OK", {"price": price, "address": address, "phone": phone}

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    # 1. Получаем список всех активных каналов из базы
    try:
        res_channels = supabase.table("channels_passport").select("channel_id").eq("status", "active").execute()
        active_channels = [row['channel_id'] for row in res_channels.data]
    except Exception as e:
        print(f"❌ Ошибка получения списка каналов: {e}")
        return

    # 2. Установка периода сбора (последние 48 часов)
    start_date = datetime.now(timezone.utc) - timedelta(days=2)
    print(f"🚀 Старт агрегатора. Каналов: {len(active_channels)}. Сбор с {start_date.strftime('%d.%m %H:%M')}")

    for db_channel_id in active_channels:
        # Убираем @ для Telethon
        channel_user = db_channel_id.replace('@', '')
        print(f"📡 Сканирую {db_channel_id}...")
        
        saved_count = 0
        try:
            async for msg in client.iter_messages(channel_user, limit=100):
                if not msg.text: continue
                if msg.date < start_date: break # Ушли глубже 48 часов

                status, data = parse_post_logic(msg.text)
                
                if status == "OK":
                    try:
                        supabase.table("rposts").insert({
                            "channel_id": db_channel_id,
                            "post_text": msg.text.strip()[:1000],
                            "price": data['price'],
                            "address": data['address'],
                            "phone": data['phone']
                        }).execute()
                        saved_count += 1
                    except:
                        # Обычно это ошибка дубликата, если пост уже в базе
                        continue
            
            if saved_count > 0:
                print(f"   ✅ Новых объявлений: {saved_count}")
        
        except Exception as e:
            print(f"   ⚠️ Ошибка при чтении {db_channel_id}: {e}")
            continue

    print(f"🏁 Сбор завершен в {datetime.now().strftime('%H:%M')}")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
