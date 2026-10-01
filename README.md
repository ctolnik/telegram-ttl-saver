# telegram-ttl-saver

Python-userbot на официальном [MTProto API](https://core.telegram.org/api) (Telethon). Скачивает самоуничтожающиеся и view-once медиа **вашего** аккаунта до того, как официальный клиент вызовет `messages.readMessageContents` — после этого сервер запускает таймер удаления.

Секретные чаты (E2E) не поддерживаются: у них отдельный протокол.

## Возможности

- слушает входящие TTL / view-once фото, видео, голосовые, кружочки и документы;
- при старте может догнать последние сообщения в диалогах;
- не помечает медиа просмотренным (нет `mark_read` / `readMessageContents`);
- рядом с файлом пишет JSON с чатом, отправителем и TTL;
- не качает повторно уже сохранённые сообщения.

## Требования

- Python 3.10+
- `api_id` и `api_hash` с [my.telegram.org](https://my.telegram.org) → *API development tools*

## Установка

```powershell
git clone https://github.com/ctolnik/telegram-ttl-saver.git
cd telegram-ttl-saver
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

На Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните в `.env`:

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
TELEGRAM_SESSION=ttl_saver
TTL_SAVE_DIR=saved
TTL_CATCHUP_LIMIT=100
```

`.env`, `*.session` и каталог `saved/` в git не попадают.

## Запуск

Первый вход спросит номер телефона, код из Telegram и, если включена облачная 2FA, пароль. Сессия сохранится в `ttl_saver.session`.

```powershell
python save_ttl_media.py
```

Режимы:

| Команда | Что делает |
|---|---|
| `python save_ttl_media.py` | догоняет историю и слушает новые TTL |
| `python save_ttl_media.py --once` | только история, без фонового слушателя |
| `python save_ttl_media.py --catchup 0` | не сканировать историю, только новые |
| `python save_ttl_media.py -v` | подробные логи |

Пока скрипт работает, **не открывайте** TTL-медиа в обычном клиенте: просмотр там помечает файл просмотренным, и сервер его уничтожит.

## Куда пишутся файлы

По умолчанию — в `saved/`:

```
saved/
  123456_789_20261002_090015_alice_photo.jpg
  123456_789_20261002_090015_alice_photo.jpg.json
```

Имя: `{chat_id}_{message_id}_{utc}_{sender}_{kind}`. В JSON — чат, отправитель, TTL, признак view-once и подпись.

## Тесты

```powershell
pip install -r requirements-dev.txt
pytest
```

Живой Telegram не нужен: клиент и типы сообщений мокаются.

## Ограничения

- Нужен user-аккаунт, не бот-токен: Bot API не отдаёт TTL-медиа целиком.
- Секретные чаты не поддерживаются.
- Если медиа уже открыли в официальном клиенте, сервер мог его удалить — скрипт скачает только то, что ещё доступно.
- Telegram может ограничивать сторонние клиенты; ключи берите только на свой аккаунт.

## Безопасность

Скрипт обходит задумку отправителя «посмотреть и забыть». Используйте только для медиа, которое вам можно хранить. Не публикуйте `.env` и `.session` — это полный доступ к аккаунту.

## Лицензия

MIT. См. [LICENSE](LICENSE).
