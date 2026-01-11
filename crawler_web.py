import os, asyncio, httpx, re
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

async def crawl_channel(channel_id, username):
    url = f"https://t.me/s/{username}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        # Ищем все юзернеймы @username и ссылки t.me/
        found_usernames = set(re.findall(r'@([a-zA-Z0-9_]{5,32})', resp.text))
        
        for found in found_usernames:
            found = found.lower()
            # Сохраняем новый найденный канал
            new_channel = supabase.table("channels").upsert(
                {"username": found, "stage": "new", "source": "web_crawler"}, 
                on_conflict="username"
            ).execute()
            
            # Если сохранение успешно, создаем связь в графе
            if new_channel.data:
                to_id = new_channel.data[0]['id']
                supabase.table("channel_relations").upsert({
                    "from_channel_id": channel_id,
                    "to_channel_id": to_id,
                    "relation_type": "mention"
                }, on_conflict="from_channel_id,to_channel_id").execute()

async def main():
    # Берем каналы, которые еще не обходили
    res = supabase.table("channels").select("id, username").filter("stage", "eq", "seed").execute()
    for row in res.data:
        await crawl_channel(row['id'], row['username'])
        # Меняем статус на "обработан"
        supabase.table("channels").update({"stage": "crawled"}).eq("id", row['id']).execute()
        await asyncio.sleep(2) # Задержка для защиты

if __name__ == "__main__":
    asyncio.run(main())
