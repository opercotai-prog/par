import asyncio
import os
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"Не задана переменная окружения {name}. "
            "Добавьте ее в GitHub Secrets."
        )

    return value.strip()


def get_dialog_type(entity) -> str | None:
    if isinstance(entity, Channel):
        if entity.megagroup:
            return "GROUP"
        return "CHANNEL"

    if isinstance(entity, Chat):
        return "GROUP"

    return None


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

        me = await client.get_me()

        print(
            f"Аккаунт: id={me.id}, "
            f"username={getattr(me, 'username', None)}"
        )
        print()
        print("ДОСТУПНЫЕ ГРУППЫ, ЧАТЫ И КАНАЛЫ:")
        print("=" * 110)

        count = 0

        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            dialog_type = get_dialog_type(entity)

            if not dialog_type:
                continue

            username = getattr(entity, "username", None)
            entity_id = getattr(entity, "id", None)
            access_hash = getattr(entity, "access_hash", None)

            print(
                f"INDEX={count} | "
                f"TYPE={dialog_type} | "
                f"TITLE={dialog.name!r} | "
                f"USERNAME={username!r} | "
                f"ID={entity_id} | "
                f"ACCESS_HASH={access_hash}"
            )

            count += 1

        print("=" * 110)
        print(f"Всего источников: {count}")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        sys.exit(1)
