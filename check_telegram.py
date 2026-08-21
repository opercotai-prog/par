import asyncio
import os
import sys
from datetime import timezone

from telethon import TelegramClient
from telethon.sessions import StringSession


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"Не задана переменная окружения {name}. "
            f"Добавьте ее в GitHub Secrets."
        )

    return value


def format_date(message_date) -> str:
    if not message_date:
        return "дата неизвестна"

    if message_date.tzinfo is None:
        message_date = message_date.replace(tzinfo=timezone.utc)

    return message_date.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


async def main() -> None:
    api_id_raw = get_required_env("TG_API_ID")
    api_hash = get_required_env("TG_API_HASH")
    session_string = get_required_env("TG_SESSION_STRING")
    channel = get_required_env("TG_CHANNEL")

    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise RuntimeError("TG_API_ID должен быть числом.") from exc

    print("Подключение к Telegram...")
    print(f"Канал: {channel}")

    client = TelegramClient(
        StringSession(session_string),
        api_id,
        api_hash,
    )

    try:
        await client.connect()

        if not await client.is_user_authorized():
            raise RuntimeError(
                "Telegram-сессия не авторизована. "
                "Проверьте значение TG_SESSION_STRING."
            )

        entity = await client.get_entity(channel)

        print(f"Название: {getattr(entity, 'title', channel)}")
        print("Получение последних сообщений...")
        print("-" * 80)

        count = 0

        async for message in client.iter_messages(entity, limit=20):
            text = message.text or "[сообщение без текста]"

            print(f"ID: {message.id}")
            print(f"Дата: {format_date(message.date)}")
            print("Текст:")
            print(text)
            print(f"Ссылка: https://t.me/{channel.lstrip('@')}/{message.id}")
            print("-" * 80)

            count += 1

        print(f"Всего выведено сообщений: {count}")

    finally:
        await client.disconnect()
        print("Соединение с Telegram закрыто.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        sys.exit(1)
