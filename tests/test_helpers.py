from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto, MessageMediaWebPage

import save_ttl_media as ttl


def _message(*, media=None, **kwargs):
    defaults = {
        "media": media,
        "photo": None,
        "video": None,
        "voice": None,
        "video_note": None,
        "gif": None,
        "document": None,
        "chat_id": 111,
        "id": 22,
        "message": "",
        "sender_id": 333,
        "date": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_ttl_seconds_photo() -> None:
    media = MagicMock(spec=MessageMediaPhoto)
    media.ttl_seconds = 15
    assert ttl.ttl_seconds(_message(media=media)) == 15


def test_ttl_seconds_document() -> None:
    media = MagicMock(spec=MessageMediaDocument)
    media.ttl_seconds = 60
    assert ttl.ttl_seconds(_message(media=media)) == 60


def test_ttl_seconds_view_once_sentinel() -> None:
    media = MagicMock(spec=MessageMediaPhoto)
    media.ttl_seconds = 2_147_483_647
    assert ttl.ttl_seconds(_message(media=media)) == 2_147_483_647
    assert ttl.is_ttl_media(_message(media=media))


@pytest.mark.parametrize("value", [None, 0, -1])
def test_ttl_seconds_absent(value) -> None:
    media = MagicMock(spec=MessageMediaPhoto)
    media.ttl_seconds = value
    assert ttl.ttl_seconds(_message(media=media)) is None
    assert not ttl.is_ttl_media(_message(media=media))


def test_ttl_seconds_ignores_webpage() -> None:
    media = MagicMock(spec=MessageMediaWebPage)
    media.ttl_seconds = 10
    assert ttl.ttl_seconds(_message(media=media)) is None


def test_ttl_seconds_no_media() -> None:
    assert ttl.ttl_seconds(_message(media=None)) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("alice", "alice"),
        ("Иван Петров", "Иван_Петров"),
        ("a/b\\c:d*e?", "a_b_c_d_e"),
        ("...", "unknown"),
        ("", "unknown"),
        ("x" * 50, "x" * 40),
    ],
)
def test_safe_fragment(value: str, expected: str) -> None:
    assert ttl.safe_fragment(value) == expected


@pytest.mark.parametrize(
    ("flag", "kind"),
    [
        ("photo", "photo"),
        ("video", "video"),
        ("voice", "voice"),
        ("video_note", "video_note"),
        ("gif", "gif"),
        ("document", "document"),
    ],
)
def test_media_kind(flag: str, kind: str) -> None:
    kwargs = {flag: object()}
    assert ttl.media_kind(_message(**kwargs)) == kind


def test_media_kind_fallback() -> None:
    assert ttl.media_kind(_message()) == "media"


def test_already_saved_prefers_media_over_json(tmp_path: Path) -> None:
    media = tmp_path / "111_22_20260101_photo.jpg"
    media.write_bytes(b"img")
    (tmp_path / "111_22_20260101_photo.jpg.json").write_text("{}", encoding="utf-8")
    found = ttl.already_saved(tmp_path, _message())
    assert found == media


def test_already_saved_ignores_json_only(tmp_path: Path) -> None:
    (tmp_path / "111_22_meta.json").write_text("{}", encoding="utf-8")
    assert ttl.already_saved(tmp_path, _message()) is None


def test_already_saved_empty_dir(tmp_path: Path) -> None:
    assert ttl.already_saved(tmp_path, _message()) is None


def test_env_int_reads_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TTL_CATCHUP_LIMIT", "25")
    assert ttl.env_int("TTL_CATCHUP_LIMIT") == 25


def test_env_int_default_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TTL_CATCHUP_LIMIT", "  ")
    assert ttl.env_int("TTL_CATCHUP_LIMIT", 7) == 7


def test_env_int_missing_without_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    with pytest.raises(SystemExit, match="TELEGRAM_API_ID"):
        ttl.env_int("TELEGRAM_API_ID")


def test_parse_args_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TTL_CATCHUP_LIMIT", "40")
    monkeypatch.setattr("sys.argv", ["save_ttl_media.py"])
    args = ttl.parse_args()
    assert args.catchup == 40
    assert args.once is False
    assert args.verbose is False


def test_parse_args_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["save_ttl_media.py", "--once", "--catchup", "0", "-v"])
    args = ttl.parse_args()
    assert args.once is True
    assert args.catchup == 0
    assert args.verbose is True
