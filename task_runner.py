import os
import re
import hashlib
import asyncio
import json
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# --- КЛЮЧИ И НАСТРОЙКИ ---
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_str = os.getenv("TG_SESSION_STRING")
supabase_url = os.getenv("SUPABASEE_URL")
supabase_key = os.getenv("SUPABASEE_KEY")
gemini_key = os.getenv("GEMINI_KEY")

supabase = create_client(supabase_url, supabase_key)

# --- УНИВЕРСАЛЬНЫЙ ИИ-АНАЛИЗАТОР ---
def analyze_with_semantic_passport(text, city, config):
    """
    Использует ИИ для извлечения Ядра и Хвоста на основе правил из Паспорта канала.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    
    # Вытягиваем инструкции из паспорта
    instructions = config.get('ai_parsing_instructions', {})
    core_req = config.get('semantic_core', {}).get('required', [])
    tail_fields = config.get('metadata_tail', {}).get('available_fields', [])

    prompt = f"""
    Ты — эксперт по недвижимости в г. {city}. Проанализируй пост и выдели данные.
    
    ИНСТРУКЦИИ ДЛЯ ЭТОГО КАНАЛА:
    - Логика цен: {instructions.get('price_logic')}
    - Логика адреса: {instructions.get('address_logic')}
    - Логика залога: {instructions.get('deposit_logic', 'извлеки сумму залога если есть')}
    
    ОБЯЗАТЕЛЬНОЕ ЯДРО (CORE): {core_req}
    ДОПОЛНИТЕЛЬНЫЙ ХВОСТ (TAIL): {tail_fields}

    ТЕКСТ ПОСТА:
    "{text}"

    Верни ТОЛЬКО JSON:
    {{
      "is_offer": bool (это объявление о сдаче?),
      "core": {{ "price": int, "category": str, "address": str, "phone": str }},
      "tail": {{ "deposit": int, "utilities_separate": bool, "residential_complex": str, "pets_allowed": bool, "appliances": [] }},
      "clean_description": "текст без ссылок и мусора (до 300 симв)",
      "comment": "почему такое решение"
    }}
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        response = requests.post(url, json=payload, timeout=20)
        if response.status_code == 200:
            raw_answer = response.json()['candidates'][0]['content']['parts'][0]['text']
            cleaned = re.sub(r'```json|```', '', raw_answer).strip()
            return json.loads(cleaned)
    except Exception as e:
        print(f"      ⚠️ Ошибка ИИ: {e}")
    return None

async def run_task():
    client = TelegramClient(StringSession(session_str), api_id, api_hash)
    await client.start()

    # 1. Берем все активные каналы, у которых ЕСТЬ паспорт (parser_config)
    channels_res = supabase.table("channels").select("*").not__.is_("parser_config", "null").eq("is_active", True).execute()
    
    for ch in channels_res.data:
        conf = ch['parser_config']
        last_id = ch.get('last_message_id', 0)
        city = conf.get('semantic_core', {}).get('defaults', {}).get('city', 'Тюмень')
        
        print(f"📺 Обработка канала @{ch['username']} (с #{last_id})")

        # 2. Собираем новые сообщения (пачками по 50 для стабильности)
        async for msg in client.iter_messages(ch['username'], min_id=last_id, reverse=True, limit=50):
            if not msg.text or len(msg.text) < 30: continue
            
            # Быстрый "грубый" фильтр мусора по маркерам из паспорта (экономим токены)
            is_spam = any(marker.lower() in msg.text.lower() for marker in conf.get('extraction_rules', {}).get('is_spam_markers', []))
            if is_spam:
                print(f"   ⏩ Пост {msg.id} пропущен (маркер спама)")
                last_id = msg.id
                continue

            # 3. ГЛУБОКИЙ АНАЛИЗ (ИИ по правилам паспорта)
            print(f"   🔍 Пост {msg.id}: Анализ через Семантическое Ядро...")
            ai_data = analyze_with_semantic_passport(msg.text, city, conf)
            
            if not ai_data or not ai_data.get('is_offer'):
                print(f"   ⏩ Пост {msg.id} пропущен (не предложение или ошибка ИИ)")
                last_id = msg.id
                continue

            # 4. ПОДГОТОВКА И ЗАПИСЬ ДАННЫХ
            core = ai_data.get('core', {})
            tail = ai_data.get('tail', {})
            clean_text = ai_data.get('clean_description', msg.text[:300])
            content_hash = hashlib.md5(clean_text.encode()).hexdigest()

            post_data = {
                "channel_id": ch['id'],
                "telegram_msg_id": msg.id,
                "deal_type": "rent",
                "category": core.get('category', 'other'),
                "price": core.get('price', 0),
                "city": city,
                "raw_text_cleaned": clean_text,
                "content_hash": content_hash,
                "details": {
                    "tail": tail,
                    "ai_comment": ai_data.get('comment'),
                    "full_raw_text": msg.text[:500]
                }
            }

            try:
                # Вставка в таблицу posts
                ins_res = supabase.table("posts").insert(post_data).execute()
                
                if ins_res.data:
                    # Вставка в таблицу contacts (Шаг 3)
                    p_id = ins_res.data[0]['id']
                    phones = [core.get('phone')] if core.get('phone') else []
                    # Если ИИ не нашел телефон, попробуемRegex как подстраховку
                    if not phones:
                        phones = re.findall(r'\+?\d{10,12}', msg.text)

                    supabase.table("contacts").insert({
                        "post_id": p_id,
                        "phones": phones,
                        "links": {"msg_url": f"https://t.me/{ch['username']}/{msg.id}"}
                    }).execute()
                    
                    print(f"   ✅ ДОБАВЛЕН: #{msg.id} | {core.get('price')} руб | {core.get('category')}")
            except Exception as e:
                if "duplicate key" not in str(e):
                    print(f"   ❌ Ошибка записи {msg.id}: {e}")

            last_id = msg.id

        # 5. Обновляем точку остановки для канала
        supabase.table("channels").update({"last_message_id": last_id}).eq("id", ch['id']).execute()

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_task())
