import asyncio
import logging
import json
import os
from datetime import datetime, timedelta
from typing import Dict

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
AUTO_REPLY_DELAY = int(os.getenv("AUTO_REPLY_DELAY", 300))

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ====================== КОНФИГ ======================
CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "text": "Привет! Я сейчас занят, отвечу чуть позже 🙏",
        "photo_file_id": None,
        "animation_file_id": None,
        "reviews_chat_id": None
    }

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

config = load_config()

last_admin_reply: Dict[int, datetime] = {}
pending_tasks: Dict[int, asyncio.Task] = {}

# ====================== СОСТОЯНИЯ ======================
class ReviewStates(StatesGroup):
    waiting_for_review = State()

# ====================== КЛАВИАТУРЫ ======================
def anonymity_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Анонимно", callback_data="review_anon"),
            InlineKeyboardButton(text="С именем", callback_data="review_public")
        ]
    ])

# ====================== КОМАНДЫ АДМИНА ======================

@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    user_id = message.from_user.id

    # Если человек пришёл по ссылке отзывов
    if command.args == "review":
        await state.set_state(ReviewStates.waiting_for_review)
        await message.answer(
            "Напиши свой отзыв одним сообщением.\n"
            "После этого я спрошу, публиковать анонимно или с именем."
        )
        return

    if user_id == ADMIN_ID:
        await message.answer(
            "<b>Nox Secretary</b> — панель управления\n\n"
            "<b>Основные команды:</b>\n"
            "/set_text <текст> — текст авто-ответа\n"
            "/set_photo — сохранить фото для авто-ответа\n"
            "/set_gif — сохранить гифку для авто-ответа\n"
            "/clear_media — убрать медиа\n"
            "/status — текущие настройки\n\n"
            "<b>Отзывы:</b>\n"
            "/set_reviews_chat — установить чат для отзывов (перешли сообщение из чата)\n"
            "/review_link — получить ссылку для сбора отзывов\n",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.answer("Привет! Напиши свой вопрос — я передам администратору.")

@dp.message(Command("status"))
async def cmd_status(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    media = "нет"
    if config.get("photo_file_id"):
        media = "фото"
    elif config.get("animation_file_id"):
        media = "гифка"

    reviews_chat = config.get("reviews_chat_id") or "не установлен"

    await message.answer(
        f"<b>Настройки:</b>\n\n"
        f"Текст авто-ответа: {config['text']}\n"
        f"Медиа: {media}\n"
        f"Задержка: {AUTO_REPLY_DELAY} сек\n"
        f"Чат отзывов: <code>{reviews_chat}</code>",
        parse_mode=ParseMode.HTML
    )

@dp.message(Command("set_text"))
async def cmd_set_text(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.replace("/set_text", "", 1).strip()
    if not text:
        await message.answer("Пример:\n/set_text Привет! Я сейчас занят 🙏")
        return
    config["text"] = text
    save_config(config)
    await message.answer(f"✅ Текст обновлён:\n\n{text}")

@dp.message(Command("set_photo"))
async def cmd_set_photo(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Отправь фото, которое будет уходить в авто-ответе.")

@dp.message(Command("set_gif"))
async def cmd_set_gif(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Отправь гифку (animation), которая будет уходить в авто-ответе.")

@dp.message(Command("clear_media"))
async def cmd_clear_media(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    config["photo_file_id"] = None
    config["animation_file_id"] = None
    save_config(config)
    await message.answer("✅ Медиа удалено")

@dp.message(Command("set_reviews_chat"))
async def cmd_set_reviews_chat(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "Перешли мне любое сообщение из того чата/канала, куда нужно публиковать отзывы.\n"
        "Бот должен быть там администратором."
    )

@dp.message(Command("review_link"))
async def cmd_review_link(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    if not config.get("reviews_chat_id"):
        await message.answer("Сначала установи чат для отзывов командой /set_reviews_chat")
        return

    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=review"

    await message.answer(
        f"<b>Ссылка для сбора отзывов:</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"Кидай её людям. Они нажмут Старт и смогут оставить отзыв.",
        parse_mode=ParseMode.HTML
    )

# ====================== СОХРАНЕНИЕ МЕДИА ======================

@dp.message(F.photo, F.from_user.id == ADMIN_ID)
async def save_photo(message: Message):
    config["photo_file_id"] = message.photo[-1].file_id
    config["animation_file_id"] = None
    save_config(config)
    await message.answer("✅ Фото сохранено для авто-ответа")

@dp.message(F.animation, F.from_user.id == ADMIN_ID)
async def save_gif(message: Message):
    config["animation_file_id"] = message.animation.file_id
    config["photo_file_id"] = None
    save_config(config)
    await message.answer("✅ Гифка сохранена для авто-ответа")

# ====================== УСТАНОВКА ЧАТА ОТЗЫВОВ ======================

@dp.message(F.forward_from_chat, F.from_user.id == ADMIN_ID)
async def set_reviews_chat_from_forward(message: Message):
    chat_id = message.forward_from_chat.id
    config["reviews_chat_id"] = chat_id
    save_config(config)
    await message.answer(f"✅ Чат для отзывов установлен:\n<code>{chat_id}</code>", parse_mode=ParseMode.HTML)

# ====================== ОТЗЫВЫ ======================

@dp.message(ReviewStates.waiting_for_review)
async def process_review_text(message: Message, state: FSMContext):
    await state.update_data(review_text=message.text)
    await message.answer(
        "Отправить отзыв анонимно или с твоим именем?",
        reply_markup=anonymity_keyboard()
    )
    await state.set_state(None)

@dp.callback_query(F.data.in_({"review_anon", "review_public"}))
async def process_anonymity(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    review_text = data.get("review_text")

    if not review_text:
        await callback.answer("Что-то пошло не так, напиши отзыв заново", show_alert=True)
        return

    is_anonymous = callback.data == "review_anon"
    user = callback.from_user

    if is_anonymous:
        final_text = f"<b>Анонимный отзыв:</b>\n\n{review_text}"
    else:
        username = f"@{user.username}" if user.username else "без username"
        final_text = (
            f"<b>Отзыв от {user.full_name}</b> ({username})\n\n"
            f"{review_text}"
        )

    reviews_chat_id = config.get("reviews_chat_id")
    if not reviews_chat_id:
        await callback.message.answer("Ошибка: чат для отзывов не установлен.")
        return

    try:
        await bot.send_message(reviews_chat_id, final_text, parse_mode=ParseMode.HTML)
        await callback.message.edit_text("✅ Отзыв успешно отправлен!")
    except Exception as e:
        await callback.message.answer(f"❌ Не удалось опубликовать отзыв: {e}")

    await state.clear()
    await callback.answer()

# ====================== СООБЩЕНИЯ ОТ ЛЮДЕЙ (СЕКРЕТАРЬ) ======================

@dp.message(F.chat.type == "private", F.from_user.id != ADMIN_ID)
async def user_message(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == ReviewStates.waiting_for_review.state:
        return

    user_id = message.from_user.id
    name = message.from_user.full_name

    await message.forward(ADMIN_ID)
    await bot.send_message(
        ADMIN_ID,
        f"📩 <b>{name}</b> (ID: <code>{user_id}</code>)\n"
        f"Ответь на пересланное сообщение, чтобы сбросить таймер.",
        parse_mode=ParseMode.HTML
    )

    if user_id in pending_tasks:
        pending_tasks[user_id].cancel()

    task = asyncio.create_task(send_auto_reply(user_id))
    pending_tasks[user_id] = task

async def send_auto_reply(user_id: int):
    try:
        await asyncio.sleep(AUTO_REPLY_DELAY)

        last = last_admin_reply.get(user_id)
        if last and (datetime.now() - last) < timedelta(seconds=AUTO_REPLY_DELAY + 5):
            return

        text = config["text"]

        if config.get("photo_file_id"):
            await bot.send_photo(user_id, config["photo_file_id"], caption=text)
        elif config.get("animation_file_id"):
            await bot.send_animation(user_id, config["animation_file_id"], caption=text)
        else:
            await bot.send_message(user_id, text)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error(f"Ошибка авто-ответа: {e}")
    finally:
        pending_tasks.pop(user_id, None)

# ====================== ОТВЕТЫ АДМИНА ======================

@dp.message(F.chat.type == "private", F.from_user.id == ADMIN_ID)
async def admin_reply(message: Message):
    if message.reply_to_message and message.reply_to_message.forward_from:
        user_id = message.reply_to_message.forward_from.id

        last_admin_reply[user_id] = datetime.now()
        if user_id in pending_tasks:
            pending_tasks[user_id].cancel()
            pending_tasks.pop(user_id, None)

        try:
            if message.photo:
                await bot.send_photo(user_id, message.photo[-1].file_id, caption=message.caption)
            elif message.animation:
                await bot.send_animation(user_id, message.animation.file_id, caption=message.caption)
            elif message.video:
                await bot.send_video(user_id, message.video.file_id, caption=message.caption)
            elif message.document:
                await bot.send_document(user_id, message.document.file_id, caption=message.caption)
            else:
                await bot.send_message(user_id, message.text or "")
            await message.answer("✅ Отправлено")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")

# ====================== ЗАПУСК ======================

async def main():
    logging.basicConfig(level=logging.INFO)
    print("Nox Secretary запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
