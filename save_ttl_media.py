#!/usr/bin/env python3
"""Сохранение TTL / view-once медиа из Telegram на свой аккаунт.

Работает как userbot через официальный MTProto API (Telethon): слушает
входящие сообщения вашего аккаунта и скачивает самоуничтожающиеся фото,
видео, голосовые и документы до того, как официальный клиент вызовет
messages.readMessageContents (после этого сервер запускает таймер удаления).

Не поддерживает секретные чаты (E2E) — у них другой протокол.

Нужны api_id и api_hash с https://my.telegram.org
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.types import Message, MessageMediaDocument, MessageMediaPhoto

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv необязателен, если переменные уже в окружении
    def load_dotenv() -> None:  # type: ignore[misc]
        return None

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

LOG = logging.getLogger("ttl-saver")

SAFE_NAME = re.compile(r"[^\w.\-]+", re.UNICODE)


def env_int(name: str, default: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        if default is None:
            raise SystemExit(f"Задайте {name} в .env или окружении")
        return default
    return int(raw)


def ttl_seconds(message: Message) -> int | None:
    """Секунды TTL у медиа, включая sentinel view-once (2147483647)."""
    media = message.media
    if not isinstance(media, (MessageMediaPhoto, MessageMediaDocument)):
        return None
    ttl = getattr(media, "ttl_seconds", None)
    if ttl is None or ttl <= 0:
        return None
    return int(ttl)


def is_ttl_media(message: Message) -> bool:
    return ttl_seconds(message) is not None


def safe_fragment(value: str, limit: int = 40) -> str:
    cleaned = SAFE_NAME.sub("_", value).strip("._")
    return (cleaned or "unknown")[:limit]


def media_kind(message: Message) -> str:
    if message.photo:
        return "photo"
    if message.video:
        return "video"
    if message.voice:
        return "voice"
    if message.video_note:
        return "video_note"
    if message.gif:
        return "gif"
    if message.document:
        return "document"
    return "media"


async def sender_label(message: Message) -> str:
    sender = await message.get_sender()
    if sender is None:
        return "unknown"
    username = getattr(sender, "username", None)
    if username:
        return str(username)
    first = getattr(sender, "first_name", None) or ""
    last = getattr(sender, "last_name", None) or ""
    name = f"{first} {last}".strip()
    if name:
        return name
    title = getattr(sender, "title", None)
    if title:
        return str(title)
    return str(getattr(sender, "id", "unknown"))


async def chat_label(message: Message) -> str:
    chat = await message.get_chat()
    if chat is None:
        return str(message.chat_id)
    title = getattr(chat, "title", None)
    if title:
        return str(title)
    username = getattr(chat, "username", None)
    if username:
        return str(username)
    first = getattr(chat, "first_name", None) or ""
    last = getattr(chat, "last_name", None) or ""
    name = f"{first} {last}".strip()
    return name or str(message.chat_id)


def already_saved(save_dir: Path, message: Message) -> Path | None:
    prefix = f"{message.chat_id}_{message.id}_"
    matches = list(save_dir.glob(f"{prefix}*"))
    media_matches = [p for p in matches if p.suffix.lower() != ".json"]
    if media_matches:
        return media_matches[0]
    return None


async def save_message(client: TelegramClient, message: Message, save_dir: Path) -> Path | None:
    ttl = ttl_seconds(message)
    if ttl is None:
        return None

    existing = already_saved(save_dir, message)
    if existing:
        LOG.info("уже есть %s", existing.name)
        return existing

    save_dir.mkdir(parents=True, exist_ok=True)

    kind = media_kind(message)
    sender = await sender_label(message)
    chat = await chat_label(message)
    when = message.date.astimezone(timezone.utc) if message.date else datetime.now(timezone.utc)
    stamp = when.strftime("%Y%m%d_%H%M%S")
    base = f"{message.chat_id}_{message.id}_{stamp}_{safe_fragment(sender)}_{kind}"

    LOG.info(
        "скачиваю ttl=%s kind=%s chat=%s sender=%s msg=%s",
        ttl if ttl < 2_000_000_000 else "view-once",
        kind,
        chat,
        sender,
        message.id,
    )

    path = await client.download_media(message, file=str(save_dir / base))
    if not path:
        LOG.warning("пустое медиа: chat=%s msg=%s", message.chat_id, message.id)
        return None

    saved = Path(path)
    meta = {
        "chat_id": message.chat_id,
        "chat": chat,
        "message_id": message.id,
        "sender": sender,
        "sender_id": message.sender_id,
        "date_utc": when.isoformat(),
        "ttl_seconds": ttl,
        "view_once": ttl >= 2_000_000_000,
        "kind": kind,
        "file": saved.name,
        "text": message.message or "",
    }
    saved.with_suffix(saved.suffix + ".json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LOG.info("сохранено %s", saved)
    return saved


async def catch_up(client: TelegramClient, save_dir: Path, per_dialog: int) -> int:
    saved = 0
    async for dialog in client.iter_dialogs():
        async for message in client.iter_messages(dialog, limit=per_dialog):
            if not is_ttl_media(message):
                continue
            path = await save_message(client, message, save_dir)
            if path:
                saved += 1
    return saved


async def run(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    api_id = env_int("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    if not api_hash:
        raise SystemExit("Задайте TELEGRAM_API_HASH в .env или окружении")

    session = os.getenv("TELEGRAM_SESSION", str(ROOT / "ttl_saver"))
    save_dir = Path(os.getenv("TTL_SAVE_DIR", str(ROOT / "saved"))).expanduser()
    catch_limit = env_int("TTL_CATCHUP_LIMIT", args.catchup)

    client = TelegramClient(session, api_id, api_hash)

    @client.on(events.NewMessage(incoming=True, func=lambda e: is_ttl_media(e.message)))
    async def on_ttl(event: events.NewMessage.Event) -> None:
        # Не вызываем mark_read / readMessageContents — иначе сервер
        # запускает таймер самоуничтожения.
        try:
            await save_message(client, event.message, save_dir)
        except Exception:
            LOG.exception("не удалось сохранить msg=%s", event.message.id)

    await client.start()
    me = await client.get_me()
    LOG.info("вошли как %s (id=%s)", me.username or me.first_name, me.id)
    LOG.info("каталог сохранения: %s", save_dir)

    if catch_limit > 0:
        LOG.info("догоняю последние %s сообщений в каждом диалоге", catch_limit)
        n = await catch_up(client, save_dir, catch_limit)
        LOG.info("догоняние: сохранено %s файлов", n)

    if args.once:
        await client.disconnect()
        return

    LOG.info("слушаю новые TTL-сообщения, Ctrl+C для выхода")
    await client.run_until_disconnected()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Сохранить TTL-медиа Telegram на свой аккаунт")
    parser.add_argument(
        "--once",
        action="store_true",
        help="только догнать историю и выйти, без прослушивания",
    )
    parser.add_argument(
        "--catchup",
        type=int,
        default=int(os.getenv("TTL_CATCHUP_LIMIT", "100")),
        help="сколько последних сообщений смотреть в каждом диалоге (0 = не догонять)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
