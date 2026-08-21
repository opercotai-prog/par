import asyncio
import os
import sys
from datetime import timezone

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat


TARGET_DIALOG_IDS = {
    5231114308,
    3884758964,
    3987433767,
}


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"Не задана переменная окружения {name}. "
            "Добавьте ее в GitHub Secrets."
        )

    return value.strip()


def format_date(message_date) -> str:
    if not message_date:
        return "дата неизвестна"

    if message_date.tzinfo is None:
        message_date = message_date.replace(tzinfo=timezone.utc)

    return message_date.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def get_dialog_type(entity) -> str:
    if isinstance(entity, Channel):
        return "GROUP" if entity.megagroup else "CHANNEL"

    if isinstance(entity, Chat):
        return "GROUP"

    return type(entity).__name__


async def main() -> None:
    api_id = int(get_required_env("TG_API_ID"))
    api_hash = get_required_env("TG_API_HASH")
    session_string = get_required_env("TG_SESSION_STRING")

    client = TelegramClient(
        StringSession(session_string),
        api_id,
        api_hash,
    )

    try:
        await client.connect()

        if not await client.is_user_authorized():
            raise RuntimeError("Telegram-сессия не авторизована")

        print("Подключение к Telegram выполнено")
        print(f"Целевые ID: {sorted(TARGET_DIALOG_IDS)}")
        print("=" * 100)

        found_dialogs = {}

        async for dialog in client.iter_dialogs():
            if dialog.id in TARGET_DIALOG_IDS:
                found_dialogs[dialog.id] = dialog

        if not found_dialogs:
            raise RuntimeError(
                "Ни один из указанных диалогов не найден "
                "в списке диалогов аккаунта."
            )

        for dialog_id in sorted(TARGET_DIALOG_IDS):
            dialog = found_dialogs.get(dialog_id)

            if dialog is None:
                print(f"ДИАЛОГ НЕ НАЙДЕН: ID={dialog_id}")
                print("=" * 100)
                continue

            entity = dialog.entity
            dialog_type = get_dialog_type(entity)

            print(f"ТИП: {dialog_type}")
            print(f"НАЗВАНИЕ: {dialog.name}")
            print(f"ID: {dialog.id}")
            print(f"USERNAME: {getattr(entity, 'username', None)}")
            print("ПОСЛЕДНИЕ 5 СООБЩЕНИЙ:")
            print("-" * 100)

            messages = []

            async for message in client.iter_messages(entity, limit=5):
                messages.append(message)

            if not messages:
                print("Сообщений нет или история недоступна.")
                print("=" * 100)
                continue

            for message in messages:
                text = message.text or "[сообщение без текста]"

                print(f"ID сообщения: {message.id}")
                print(f"Дата: {format_date(message.date)}")
                print("Текст:")
                print(text)
                print("-" * 100)

            print(f"Получено сообщений: {len(messages)}")
            print("=" * 100)

    finally:
        await client.disconnect()
        print("Соединение с Telegram закрыто.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        sys.exit(1)
