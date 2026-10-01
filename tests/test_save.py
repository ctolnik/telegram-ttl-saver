from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telethon.tl.types import MessageMediaPhoto

import save_ttl_media as ttl


def _ttl_message(**kwargs):
    media = MagicMock(spec=MessageMediaPhoto)
    media.ttl_seconds = kwargs.pop("ttl_seconds", 15)
    defaults = {
        "media": media,
        "photo": object(),
        "video": None,
        "voice": None,
        "video_note": None,
        "gif": None,
        "document": None,
        "chat_id": 777,
        "id": 9,
        "message": "смотри",
        "sender_id": 42,
        "date": datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
    }
    defaults.update(kwargs)
    message = SimpleNamespace(**defaults)

    async def get_sender():
        return SimpleNamespace(username="alice", first_name="A", last_name="B", id=42)

    async def get_chat():
        return SimpleNamespace(title="Личка", username=None, first_name=None, last_name=None)

    message.get_sender = get_sender
    message.get_chat = get_chat
    return message


@pytest.mark.asyncio
async def test_sender_label_username() -> None:
    assert await ttl.sender_label(_ttl_message()) == "alice"


@pytest.mark.asyncio
async def test_sender_label_full_name() -> None:
    message = _ttl_message()

    async def get_sender():
        return SimpleNamespace(username=None, first_name="Иван", last_name="Петров", id=1)

    message.get_sender = get_sender
    assert await ttl.sender_label(message) == "Иван Петров"


@pytest.mark.asyncio
async def test_sender_label_unknown() -> None:
    message = _ttl_message()

    async def get_sender():
        return None

    message.get_sender = get_sender
    assert await ttl.sender_label(message) == "unknown"


@pytest.mark.asyncio
async def test_chat_label_title() -> None:
    assert await ttl.chat_label(_ttl_message()) == "Личка"


@pytest.mark.asyncio
async def test_chat_label_fallback_id() -> None:
    message = _ttl_message()

    async def get_chat():
        return None

    message.get_chat = get_chat
    assert await ttl.chat_label(message) == "777"


@pytest.mark.asyncio
async def test_save_message_writes_file_and_sidecar(tmp_path: Path) -> None:
    message = _ttl_message()
    client = AsyncMock()

    async def download_media(_msg, file: str):
        path = Path(file).with_suffix(".jpg")
        path.write_bytes(b"jpeg")
        return str(path)

    client.download_media.side_effect = download_media

    saved = await ttl.save_message(client, message, tmp_path)
    assert saved is not None
    assert saved.exists()
    assert saved.read_bytes() == b"jpeg"

    meta_path = saved.with_suffix(saved.suffix + ".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["chat_id"] == 777
    assert meta["message_id"] == 9
    assert meta["sender"] == "alice"
    assert meta["ttl_seconds"] == 15
    assert meta["view_once"] is False
    assert meta["kind"] == "photo"
    assert meta["text"] == "смотри"
    assert meta["file"] == saved.name


@pytest.mark.asyncio
async def test_save_message_skips_non_ttl(tmp_path: Path) -> None:
    message = _ttl_message(ttl_seconds=0)
    client = AsyncMock()
    assert await ttl.save_message(client, message, tmp_path) is None
    client.download_media.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_message_skips_existing(tmp_path: Path) -> None:
    existing = tmp_path / "777_9_already.jpg"
    existing.write_bytes(b"old")
    client = AsyncMock()
    result = await ttl.save_message(client, _ttl_message(), tmp_path)
    assert result == existing
    client.download_media.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_message_empty_download(tmp_path: Path) -> None:
    client = AsyncMock()
    client.download_media.return_value = None
    assert await ttl.save_message(client, _ttl_message(), tmp_path) is None


@pytest.mark.asyncio
async def test_save_message_marks_view_once(tmp_path: Path) -> None:
    message = _ttl_message(ttl_seconds=2_147_483_647)
    client = AsyncMock()

    async def download_media(_msg, file: str):
        path = Path(file).with_suffix(".jpg")
        path.write_bytes(b"x")
        return str(path)

    client.download_media.side_effect = download_media
    saved = await ttl.save_message(client, message, tmp_path)
    meta = json.loads(saved.with_suffix(saved.suffix + ".json").read_text(encoding="utf-8"))
    assert meta["view_once"] is True


@pytest.mark.asyncio
async def test_catch_up_counts_only_ttl(tmp_path: Path) -> None:
    ttl_msg = _ttl_message()
    ordinary = SimpleNamespace(media=None)

    async def iter_dialogs():
        yield object()

    async def iter_messages(_dialog, limit: int):
        assert limit == 5
        yield ordinary
        yield ttl_msg

    client = AsyncMock()
    client.iter_dialogs = iter_dialogs
    client.iter_messages = iter_messages

    async def download_media(_msg, file: str):
        path = Path(file).with_suffix(".jpg")
        path.write_bytes(b"x")
        return str(path)

    client.download_media.side_effect = download_media
    assert await ttl.catch_up(client, tmp_path, 5) == 1
    assert list(tmp_path.glob("*.jpg"))
