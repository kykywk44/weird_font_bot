import asyncio
import json
import logging
import os

from aiohttp import web

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions

# Конфигурация из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")
ADMIN_ID = int(os.getenv("ADMIN_ID", "855323286"))
FONT_FILE_NAME = os.getenv("FONT_FILE_NAME", "font.ttf")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Инициализация
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
router = Router()

# Файлы
USERS_DB_FILE = "users.json"
SETTINGS_FILE = "settings.json"


class AdminState(StatesGroup):
    waiting_for_welcome_text = State()


# ==================== БАЗА ДАННЫХ ====================

def load_users_db() -> dict:
    if not os.path.exists(USERS_DB_FILE):
        return {}
    try:
        with open(USERS_DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки базы: {e}")
        return {}


def save_users_db(data: dict) -> None:
    try:
        with open(USERS_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения базы: {e}")


def add_user(user_id: int, username: str, first_name: str) -> bool:
    db = load_users_db()
    if str(user_id) in db:
        return False
    db[str(user_id)] = {
        "username": username if username else None,
        "first_name": first_name,
        "date": None
    }
    save_users_db(db)
    return True


def get_all_users() -> list:
    return list(load_users_db().items())


def get_users_count() -> int:
    return len(load_users_db())


# ==================== НАСТРОЙКИ ====================

def load_settings() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        default_settings = {"welcome_text": None, "welcome_entities": None}
        save_settings(default_settings)
        return default_settings
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if "welcome_entities" not in data:
                data["welcome_entities"] = None
                save_settings(data)
            return data
    except Exception as e:
        logger.error(f"Ошибка загрузки настроек: {e}")
        return {"welcome_text": None, "welcome_entities": None}


def save_settings(settings: dict) -> None:
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения настроек: {e}")


async def send_welcome(message, reply_markup=None):
    """Отправляет приветственное сообщение с сохранённым форматированием"""
    settings = load_settings()

    if settings.get("welcome_text"):
        text = settings["welcome_text"]
        entities_data = settings.get("welcome_entities")

        entities = None
        if entities_data:
            from aiogram.types import MessageEntity
            entities = [MessageEntity(**e) for e in entities_data]

        await message.answer(text, reply_markup=reply_markup, entities=entities, link_preview_options=LinkPreviewOptions(is_disabled=True))
    else:
        default_text = (
            "Привет! \U0001f44b\n\n"
            "Данный шрифт предназначен только для <b>некоммерческого использования</b>.\n\n"
            "Вы можете использовать его в личных проектах бесплатно.\n"
            "Коммерческое использование запрещено без письменного разрешения автора."
        )
        await message.answer(default_text, reply_markup=reply_markup, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))



# ==================== ПАГИНАЦИЯ ====================

USERS_PER_PAGE = 10


def get_users_page(page: int) -> tuple:
    users = get_all_users()
    total = len(users)
    total_pages = (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE if total > 0 else 1
    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    return users[start:end], total, total_pages


def build_users_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons = []
    if total_pages > 1:
        row = []
        if page > 0:
            row.append(InlineKeyboardButton(text="← Назад", callback_data=f"users_page_{page - 1}"))
        if page < total_pages - 1:
            row.append(InlineKeyboardButton(text="Вперед →", callback_data=f"users_page_{page + 1}"))
        if row:
            buttons.append(row)
    buttons.append([InlineKeyboardButton(text="Закрыть", callback_data="users_close")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================== ОБРАБОТЧИКИ ====================

@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    add_user(user_id, username, first_name)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Я ознакомлен и согласен", callback_data="accept_license")]
        ]
    )
    await send_welcome(message, reply_markup=keyboard)


@router.callback_query(F.data == "accept_license")
async def accept_license(callback: CallbackQuery):
    user_id = callback.from_user.id
    font_path = __import__('pathlib').Path(FONT_FILE_NAME)

    if font_path.exists():
        try:
            await callback.message.answer("Спасибо за согласие! Вот ваш файл шрифта:")
            await callback.message.answer_document(FSInputFile(FONT_FILE_NAME))
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка отправки шрифта: {e}")
            await callback.message.answer("Произошла ошибка при отправке файла. Попробуйте позже.")
            await callback.answer()
    else:
        await callback.message.answer(
            "К сожалению, файл шрифта временно недоступен. "
            "Пожалуйста, попробуйте позже или свяжитесь с администратором @bykvv"
        )
        await callback.answer()


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return

    total = get_users_count()
    page_users, _, total_pages = get_users_page(0)

    text = f"📊 <b>Статистика бота</b>\n\n"
    text += f"Общее количество пользователей: {total}\n\n"
    text += f"<b>Пользователи (страница 1/{total_pages}):</b>\n\n"

    for user_id, user_data in page_users:
        username = user_data.get("username")
        first_name = user_data.get("first_name", "Неизвестно")
        if username:
            link = f"@{username}"
        else:
            link = first_name
        text += f"• {link}\n"

    await message.answer(text, reply_markup=build_users_keyboard(0, total_pages), link_preview_options=LinkPreviewOptions(is_disabled=True))


@router.callback_query(F.data.startswith("users_page_"))
async def users_pagination(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    page = int(callback.data.split("_")[-1])
    page_users, total, total_pages = get_users_page(page)

    text = f"📊 <b>Статистика бота</b>\n\n"
    text += f"Общее количество пользователей: {total}\n\n"
    text += f"<b>Пользователи (страница {page + 1}/{total_pages}):</b>\n\n"

    for user_id, user_data in page_users:
        username = user_data.get("username")
        first_name = user_data.get("first_name", "Неизвестно")
        if username:
            link = f"@{username}"
        else:
            link = first_name
        text += f"• {link}\n"

    await callback.message.edit_text(text, reply_markup=build_users_keyboard(page, total_pages), link_preview_options=LinkPreviewOptions(is_disabled=True))
    await callback.answer()


@router.callback_query(F.data == "users_close")
async def users_close(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


@router.message(Command("export"))
async def cmd_export(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return

    users = get_all_users()
    if not users:
        await message.answer("База пользователей пуста.")
        return

    export_file = "users_export.txt"
    try:
        with open(export_file, 'w', encoding='utf-8') as f:
            f.write(f"Всего пользователей: {len(users)}\n\n")
            f.write("ID | Username | First Name\n")
            f.write("-" * 50 + "\n")
            for user_id, user_data in users:
                username = user_data.get("username") or "Нет"
                first_name = user_data.get("first_name", "Неизвестно")
                f.write(f"{user_id} | @{username} | {first_name}\n")

        await message.answer(f"Экспорт завершен. Всего пользователей: {len(users)}")
        await message.answer_document(FSInputFile(export_file))
        os.remove(export_file)
    except Exception as e:
        logger.error(f"Ошибка экспорта: {e}")
        await message.answer(f"Ошибка при экспорте: {e}")


@router.message(Command("setwelcome"))
async def cmd_setwelcome(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return

    await message.answer(
        "Отправьте новое приветственное сообщение с любым форматированием.\n\n"
        "Бот автоматически сохранит жирный текст, курсив, ссылки и т.д.\n\n"
        "Отправьте /cancel для отмены."
    )
    await state.set_state(AdminState.waiting_for_welcome_text)


@router.message(AdminState.waiting_for_welcome_text)
async def process_welcome_text(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    if message.text and message.text.lower() == "/cancel":
        await message.answer("Настройка отменена.")
        await state.clear()
        return

    settings = load_settings()
    settings["welcome_text"] = message.text

    if message.entities:
        saved_entities = []
        for e in message.entities:
            d = {"type": e.type, "offset": e.offset, "length": e.length}
            if e.type == "text_link" and e.url:
                d["url"] = e.url
            if e.type == "text_mention" and e.user:
                d["user"] = {"id": e.user.id}
            if e.type == "custom_emoji" and e.custom_emoji_id:
                d["custom_emoji_id"] = e.custom_emoji_id
            if e.type == "code" and e.language:
                d["language"] = e.language
            saved_entities.append(d)
        settings["welcome_entities"] = saved_entities
    else:
        settings["welcome_entities"] = None

    save_settings(settings)

    await message.answer("✅ Приветственное сообщение успешно обновлено!")
    await message.answer("Результат:")
    await send_welcome(message)
    await state.clear()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await message.answer("Действие отменено.")
        await state.clear()
    else:
        await message.answer("Нет активных действий для отмены.")


@router.message(F.document)
async def handle_document(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет доступа к загрузке файлов.")
        return

    file = message.document
    file_name = file.file_name

    if not file_name.lower().endswith(('.ttf', '.otf')):
        await message.answer("Пожалуйста, загрузите файл шрифта (.ttf или .otf)")
        return

    try:
        file_path = await bot.download(file)
        with open(FONT_FILE_NAME, 'wb') as f:
            f.write(file_path.getvalue())
        logger.info(f"Админ загрузил новый файл шрифта: {file_name}")
        await message.answer("✅ Шрифт успешно обновлен!")
    except Exception as e:
        logger.error(f"Ошибка сохранения шрифта: {e}")
        await message.answer(f"Ошибка при сохранении файла: {e}")


# ==================== WEBHOOK ====================

async def on_startup(bot: Bot):
    """Регистрация вебхука"""
    if WEBHOOK_URL:
        await bot.set_webhook(f"{WEBHOOK_URL}/webhook")
        logger.info(f"Вебхук установлен: {WEBHOOK_URL}/webhook")
    else:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Вебхук удален")


async def on_shutdown(bot: Bot):
    """Удаление вебхука при остановке"""
    await bot.delete_webhook()
    logger.info("Вебхук удален")


# aiohttp обработчики
async def handle_webhook(request):
    """Обработка обновлений от Telegram"""
    try:
        update = await request.json()
        await dp.feed_webhook_update(bot, update)
        return web.Response()
    except Exception as e:
        logger.error(f"Ошибка обработки вебхука: {e}")
        return web.Response(status=500)


async def handle_health(request):
    """Health check для Render"""
    return web.Response(text="OK")


# Инициализация
dp = Dispatcher()
dp.include_router(router)
dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)

app = web.Application()
app.router.add_post("/webhook", handle_webhook)
app.router.add_get("/", handle_health)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Запуск сервера на порту {port}")
    web.run_app(app, host="0.0.0.0", port=port)