"""
Telegram-бот для скачивания видео с TikTok
Использует: aiogram 3.x + yt-dlp

Токен бота берётся из переменной окружения BOT_TOKEN
(настраивается в Railway -> Variables), в коде токена нет.

Статистика пользователей сохраняется в users.json и доступна
только администратору по команде /stats.
"""

import asyncio
import json
import logging
import os
import re
import uuid

import yt_dlp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile

# ==== НАСТРОЙКИ ====
BOT_TOKEN = os.getenv("BOT_TOKEN")
DOWNLOAD_DIR = "downloads"
MAX_FILE_SIZE_MB = 50  # лимит обычного Bot API
USERS_FILE = "users.json"
ADMIN_ID = 5420205036  # твой Telegram ID — только тебе доступна /stats

# ==== ЛОГИРОВАНИЕ ====
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise RuntimeError(
        "Не найден BOT_TOKEN. Задай переменную окружения BOT_TOKEN "
        "(в Railway: Variables -> BOT_TOKEN=твой_токен)."
    )

# ==== ИНИЦИАЛИЗАЦИЯ ====
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

TIKTOK_REGEX = re.compile(
    r"(https?://)?(www\.|vm\.|vt\.)?tiktok\.com/\S+", re.IGNORECASE
)


# ==== УЧЁТ ПОЛЬЗОВАТЕЛЕЙ ====
def load_users() -> set:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, ValueError):
            return set()
    return set()


def save_users(users: set):
    with open(USERS_FILE, "w") as f:
        json.dump(list(users), f)


def register_user(user_id: int):
    users = load_users()
    if user_id not in users:
        users.add(user_id)
        save_users(users)
        logger.info(f"Новый пользователь: {user_id} (всего: {len(users)})")


def download_tiktok(url: str) -> str:
    """Скачивает видео с TikTok и возвращает путь к файлу."""
    file_id = str(uuid.uuid4())
    output_path = os.path.join(DOWNLOAD_DIR, f"{file_id}.mp4")

    ydl_opts = {
        "outtmpl": output_path,
        "format": "mp4/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    return output_path


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    register_user(message.from_user.id)
    await message.answer(
        "Привет! Пришли мне ссылку на видео из TikTok, и я его скачаю "
        "и пришлю сюда файлом."
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    register_user(message.from_user.id)
    await message.answer(
        "Просто отправь ссылку вида:\n"
        "https://www.tiktok.com/@user/video/1234567890\n\n"
        "или короткую https://vm.tiktok.com/XXXXX/"
    )


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return  # для всех остальных бот молчит, как будто команды нет
    users = load_users()
    await message.answer(f"👥 Всего уникальных пользователей: {len(users)}")


@dp.message()
async def handle_message(message: types.Message):
    register_user(message.from_user.id)

    text = message.text or ""
    match = TIKTOK_REGEX.search(text)

    if not match:
        await message.answer(
            "Это не похоже на ссылку TikTok 🤔\n"
            "Пришли ссылку вида https://www.tiktok.com/..."
        )
        return

    url = match.group(0)
    status_msg = await message.answer("⏳ Скачиваю видео...")

    file_path = None
    try:
        file_path = await asyncio.to_thread(download_tiktok, url)

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            await status_msg.edit_text(
                f"⚠️ Видео весит {file_size_mb:.1f} МБ — это больше лимита "
                f"в {MAX_FILE_SIZE_MB} МБ для обычного Bot API. "
                "Нужен локальный Bot API Server для отправки больших файлов."
            )
            return

        video = FSInputFile(file_path)
        await message.answer_video(video, caption="Готово! ✅")
        await status_msg.delete()

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Ошибка скачивания: {e}")
        await status_msg.edit_text(
            "❌ Не удалось скачать видео. Возможно, ссылка неверна, "
            "видео приватное или удалено."
        )
    except Exception as e:
        logger.exception("Неожиданная ошибка")
        await status_msg.edit_text(f"❌ Произошла ошибка: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)


async def main():
    logger.info("Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
