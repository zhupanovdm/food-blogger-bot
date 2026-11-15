import fcntl
import logging
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from .service import Config, OpenAIAnalyzer, Service, TelegramAPI, TelegramError
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


def setup(telegram):
    """Только /whoami; фото и подписи не обрабатываются и не сохраняются."""
    print("Режим настройки. Отправь /whoami боту в группе; затем Ctrl+C.")
    offset = 0
    while True:
        for update in telegram.poll(offset, timeout=20):
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            if msg.get("text", "").split("@")[0].strip() == "/whoami" and msg.get("from"):
                telegram.send_text(msg["chat"]["id"], msg["message_id"],
                                   f"CHAT_ID={msg['chat']['id']}\nUSER_ID={msg['from']['id']}")


def main():
    os.umask(0o077)
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for name in ("httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Заполни TELEGRAM_BOT_TOKEN в .env. Инструкция — README.md.", file=sys.stderr)
        return 2
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    with (data / "bot.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("В этой папке уже запущен бот.", file=sys.stderr)
            return 2
        telegram = TelegramAPI(token)
        store = analyzer = None
        try:
            if os.getenv("SETUP_MODE", "false").lower() == "true":
                setup(telegram)
                return 0
            try:
                key = os.environ["OPENAI_API_KEY"].strip()
                if not key:
                    raise ValueError
                config = Config(token, key, os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                    int(os.environ["TELEGRAM_CHAT_ID"]), int(os.environ["TELEGRAM_OWNER_ID"]),
                    os.getenv("TIMEZONE", "Europe/Moscow"))
                ZoneInfo(config.timezone)
                if config.chat_id >= 0 or config.owner_id <= 0:
                    raise ValueError
            except (KeyError, ValueError):
                print("Проверь .env: OPENAI_API_KEY, TELEGRAM_CHAT_ID (группа), TELEGRAM_OWNER_ID, "
                      "TIMEZONE. Для получения ID: SETUP_MODE=true.", file=sys.stderr)
                return 2
            # Не удаляем настроенный webhook молча: это мог бы быть другой работающий сервис.
            if telegram.call("getWebhookInfo").get("url"):
                print("У бота настроен webhook. Используй нового бота или отключи прежнее подключение.", file=sys.stderr)
                return 2
            telegram.set_commands(config.chat_id, config.owner_id)
            store = Store(data / "food-log.sqlite3")
            analyzer = OpenAIAnalyzer(config.openai_key, config.model)
            Service(config, store, telegram, analyzer).run()
        except KeyboardInterrupt:
            print("\nБот остановлен. Дневник сохранён.")
        except TelegramError as exc:
            print(f"Telegram API: код {exc.code}. Проверь настройку бота и подключение.", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"Не удалось запустить сервис: {type(exc).__name__}. Проверь настройки и сеть.", file=sys.stderr)
            return 1
        finally:
            telegram.close()
            if analyzer:
                analyzer.close()
            if store:
                store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
