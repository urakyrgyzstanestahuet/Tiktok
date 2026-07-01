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

SUPPORTED_REGEX = re.compile(
    r"(https?://)?"
    r"("
    r"(www\.|vm\.|vt\.)?tiktok\.com/\S+"           # TikTok
    r"|(www\.)?youtube\.com/\S+"                      # YouTube
    r"|youtu\.be/\S+"                                  # YouTube short link
    r"|(www\.)?instagram\.com/\S+"                    # Instagram
    r")",
    re.IGNORECASE,
)


# ==== УЧЁТ ПОЛЬЗОВАТЕЛЕЙ ====
def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def save_users(users: dict):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, ensure_ascii=False)


def register_user(user: types.User):
    users = load_users()
    user_id = str(user.id)
    if user_id not in users:
        users[user_id] = {
            "username": user.username,
            "first_name": user.first_name,
        }
        save_users(users)
        logger.info(f"Новый пользователь: {user_id} (всего: {len(users)})")


def download_video(url: str) -> str:
    """Скачивает видео с TikTok, YouTube или Instagram и возвращает путь к файлу."""
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
    register_user(message.from_user)
    await message.answer(
        "Привет! Пришли мне ссылку на видео из TikTok, YouTube или Instagram, "
        "и я его скачаю и пришлю сюда файлом."
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    register_user(message.from_user)
    await message.answer(
        "Просто отправь ссылку вида:\n"
        "• https://www.tiktok.com/@user/video/1234567890\n"
        "• https://youtube.com/watch?v=XXXXX (или youtu.be/XXXXX)\n"
        "• https://www.instagram.com/reel/XXXXX/"
    )


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return  # для всех остальных бот молчит, как будто команды нет
    users = load_users()

    if not users:
        await message.answer("Пока нет ни одного пользователя.")
        return

    lines = [f"👥 Всего уникальных пользователей: {len(users)}\n"]
    for uid, info in users.items():
        username = info.get("username")
        first_name = info.get("first_name") or "—"
        handle = f"@{username}" if username else "(без username)"
        lines.append(f"• {first_name} {handle} — id {uid}")

    text = "\n".join(lines)

    # Telegram ограничивает сообщение 4096 символами — режем на части
    for i in range(0, len(text), 4000):
        await message.answer(text[i:i + 4000])


@dp.message()
async def handle_message(message: types.Message):
    register_user(message.from_user)

    text = message.text or ""
    match = SUPPORTED_REGEX.search(text)

    if not match:
        await message.answer(
            "Это не похоже на ссылку TikTok, YouTube или Instagram 🤔\n"
            "Пришли ссылку на видео с одной из этих площадок."
        )
        return

    url = match.group(0)
    status_msg = await message.answer("⏳ Скачиваю видео...")

    file_path = None
    try:
        file_path = await asyncio.to_thread(download_video, url)

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
