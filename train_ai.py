import os
import json
import re
import requests
from supabase import create_client

# --- НАСТРОЙКИ ---
try:
    GEMINI_KEY = os.environ['GEMINI_KEY']
    SUPABASE_URL = os.environ['SUPABASE_URL']
    SUPABASE_KEY = os.environ['SUPABASE_KEY']
except KeyError:
    print("Ошибка: Нет ключей в переменных окружения")
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def generate_rules_with_gemini(examples_text):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}"
    
    # МЕТА-ПРОМПТ: Мы учим Gemini создавать конфиг для парсера
    prompt = f"""
    Роль: Главный технолог парсинга недвижимости.
    Задача: Проанализируй список объявлений и создай JSON-конфиг для Python-парсера.
    
    ВОТ СЫРЫЕ ОБЪЯВЛЕНИЯ (EXAMPLES):
    {examples_text}
    
    ТРЕБОВАНИЯ К JSON (строгая структура):
    1. "whitelist": список слов (массив строк), которые точно указывают, что это ОБЪЯВЛЕНИЕ О СДАЧЕ (сдам, аренда, сдается...).
    2. "blacklist": список слов (массив), указывающих на СПАМ или РИЕЛТОРОВ (куплю, подбор, комиссия, напишите менеджеру...).
    3. "cities": объект, где ключ - название города (Калининград, Светлогорск), а значение - список синонимов (клд, konig, rauchen). Определи города из текстов.
    4. "regex_price": строка-регулярка (Python regex) для поиска цены (учитывай 'к', 'тыс', 'руб').
    5. "rooms_map": объект, сопоставляющий слова с числом комнат ({"студия": "0", "однушка": "1"}).

    Верни ТОЛЬКО валидный JSON. Никакого маркдауна.
    """
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, json=payload)
        result = response.json()
        raw_text = result['candidates'][0]['content']['parts'][0]['text']
        # Чистим ответ от ```json
        clean_json = re.sub(r'```json|```', '', raw_text).strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"Ошибка Gemini: {e}")
        return None

def main():
    print("🧠 ЗАПУСК ТРЕНИРОВКИ AI...")

    # 1. Берем последние 20 постов из базы (Сырье)
    response = supabase.table('ads').select('raw_text').limit(20).execute()
    posts = [row['raw_text'] for row in response.data if row['raw_text']]
    
    if not posts:
        print("❌ В базе нет постов для обучения! Сначала запусти парсер.")
        return

    print(f"📊 Анализируем {len(posts)} постов...")
    examples_str = "\n---\n".join(posts)

    # 2. Генерируем правила через Gemini
    new_rules = generate_rules_with_gemini(examples_str)
    
    if new_rules:
        print("💡 Gemini сгенерировал новые правила!")
        print(json.dumps(new_rules, indent=2, ensure_ascii=False))
        
        # 3. Сохраняем "Мозги" в базу данных
        data = {
            "id": 1,  # Всегда перезаписываем ID 1
            "config": new_rules,
            "updated_at": "now()"
        }
        # Upsert - вставит или обновит
        supabase.table('parsing_rules').upsert(data).execute()
        print("✅ Правила успешно сохранены в БД (parsing_rules)!")
    else:
        print("❌ Не удалось сгенерировать правила.")

if __name__ == '__main__':
    main()
