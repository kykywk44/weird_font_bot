import asyncio
import json
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions, MessageEntity

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Импорт конфигурации
from config import BOT_TOKEN, ADMIN_ID, FONT_FILE_NAME

# Инициализация бота
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

# FSM хранилище
storage = MemoryStorage()

router = Router()

# Пути к файлам
USERS_DB_FILE = "users.json"
SETTINGS_FILE = "settings.json"

# Машина состояний для админа
class AdminState(StatesGroup):
    waiting_for_welcome_text = State()


# ==================== БАЗА ДАННЫХ ПОЛЬЗОВАТЕЛЕЙ ====================

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
        default = {"welcome_text": None}
        save_settings(default)
        return default
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки настроек: {e}")
        return {"welcome_text": None}


def save_settings(settings: dict) -> None:
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения настроек: {e}")


# ==================== КОНВЕРТАЦИЯ ENTITIES В HTML ====================

def entities_to_html(text: str, entities: list) -> str:
    """Конвертирует MessageEntity список в HTML-строку с сохранением форматирования.
    Корректно обрабатывает перекрывающиеся entities.
    """
    if not entities:
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # Собираем все уникальные позиции границ entities
    positions = set()
    positions.add(0)
    positions.add(len(text))
    for e in entities:
        positions.add(max(0, e.offset))
        positions.add(max(0, min(e.offset + e.length, len(text))))

    sorted_positions = sorted(positions)

    # Определяем порядок тегов для правильной вложенности
    # Стилевые теги снаружи, ссылки внутри
    tag_priority = {
        'bold': 0, 'italic': 1, 'underline': 2,
        'strikethrough': 3, 'code': 4, 'pre': 5,
        'blockquote': 6, 'text_link': 7, 'text_mention': 8
    }

    def entity_to_open_tag(e: MessageEntity) -> str:
        if e.type == 'bold':
            return '<b>'
        elif e.type == 'italic':
            return '<i>'
        elif e.type == 'underline':
            return '<u>'
        elif e.type == 'strikethrough':
            return '<s>'
        elif e.type == 'code':
            return '<code>'
        elif e.type == 'pre':
            return '<pre>'
        elif e.type == 'blockquote':
            return '<blockquote>'
        elif e.type == 'text_link':
            return f'<a href="{e.url}">'
        elif e.type == 'text_mention':
            return f'<a href="tg://user?id={e.user.id}">'
        return ''

    def entity_to_close_tag(e: MessageEntity) -> str:
        if e.type == 'bold':
            return '</b>'
        elif e.type == 'italic':
            return '</i>'
        elif e.type == 'underline':
            return '</u>'
        elif e.type == 'strikethrough':
            return '</s>'
        elif e.type == 'code':
            return '</code>'
        elif e.type == 'pre':
            return '</pre>'
        elif e.type == 'blockquote':
            return '</blockquote>'
        elif e.type in ('text_link', 'text_mention'):
            return '</a>'
        return ''

    def escape(text: str) -> str:
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    result = []

    # Проходим по каждому сегменту между позициями
    for i in range(len(sorted_positions) - 1):
        seg_start = sorted_positions[i]
        seg_end = sorted_positions[i + 1]

        if seg_start >= seg_end:
            continue

        # Находим все entities, которые полностью покрывают этот сегмент
        covering = []
        for e in entities:
            e_start = max(0, e.offset)
            e_end = max(0, min(e.offset + e.length, len(text)))
            if e_start <= seg_start and e_end >= seg_end:
                covering.append(e)

        # Сортируем по приоритету (сначала стилевые, потом ссылки)
        covering.sort(key=lambda e: tag_priority.get(e.type, 99))

        # Открываем теги
        for e in covering:
            result.append(entity_to_open_tag(e))

        # Текст сегмента
        result.append(escape(text[seg_start:seg_end]))

        # Закрываем теги в обратном порядке
        for e in reversed(covering):
            result.append(entity_to_close_tag(e))

    return ''.join(result)


# ==================== ОТПРАВКА ПРИВЕТСТВИЯ ====================

async def send_welcome(message, reply_markup=None):
    """Отправляет приветственное сообщение с сохранённым форматированием"""
    settings = load_settings()

    if settings.get("welcome_text"):
        html = settings["welcome_text"]
        await message.answer(html, reply_markup=reply_markup, link_preview_options=LinkPreviewOptions(is_disabled=True))
    else:
        default_html = (
            "Привет! \U0001f44b\n\n"
            "Данный шрифт предназначен только для <b>некоммерческого использования</b>.\n\n"
            "Вы можете использовать его в личных проектах бесплатно.\n"
            "Коммерческое использование запрещено без письменного разрешения автора."
        )
        await message.answer(default_html, reply_markup=reply_markup, link_preview_options=LinkPreviewOptions(is_disabled=True))


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

    is_new = add_user(user_id, username, first_name)
    if is_new:
        logger.info(f"Новый пользователь {username or first_name} (ID: {user_id})")
    else:
        logger.info(f"Пользователь {username or first_name} (ID: {user_id}) повторно зашел")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Я ознакомлен и согласен", callback_data="accept_license")]
        ]
    )
    await send_welcome(message, reply_markup=keyboard)


@router.callback_query(F.data == "accept_license")
async def accept_license(callback: CallbackQuery):
    user_id = callback.from_user.id
    font_path = Path(FONT_FILE_NAME)

    if font_path.exists():
        try:
            await callback.message.answer("Спасибо за согласие! Вот ваш файл шрифта:")
            await callback.message.answer_document(FSInputFile(FONT_FILE_NAME))
            await callback.answer()
        except Exception as e:
            logger.error(f"Ошибка отправки шрифта пользователю {user_id}: {e}")
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

    text = "📊 <b>Статистика бота</b>\n\n"
    text += f"Общее количество пользователей: {total}\n\n"
    text += f"<b>Пользователи (страница 1/{total_pages}):</b>\n\n"

    for user_id, user_data in page_users:
        username = user_data.get("username")
        first_name = user_data.get("first_name", "Неизвестно")
        if username:
            display = f"<a href='https://t.me/{username}'>{username}</a>"
        else:
            display = first_name
        text += f"• {display}\n"

    await message.answer(text, reply_markup=build_users_keyboard(0, total_pages), link_preview_options=LinkPreviewOptions(is_disabled=True))


@router.callback_query(F.data.startswith("users_page_"))
async def users_pagination(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    page = int(callback.data.split("_")[-1])
    page_users, total, total_pages = get_users_page(page)

    text = "📊 <b>Статистика бота</b>\n\n"
    text += f"Общее количество пользователей: {total}\n\n"
    text += f"<b>Пользователи (страница {page + 1}/{total_pages}):</b>\n\n"

    for user_id, user_data in page_users:
        username = user_data.get("username")
        first_name = user_data.get("first_name", "Неизвестно")
        if username:
            display = f"<a href='https://t.me/{username}'>{username}</a>"
        else:
            display = first_name
        text += f"• {display}\n"

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
        "Бот автоматически сохранит форматирование.\n\n"
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

    # Конвертируем текст с entities в HTML
    if message.entities:
        html = entities_to_html(message.text, message.entities)
    else:
        html = message.text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # Сохраняем HTML
    settings = load_settings()
    settings["welcome_text"] = html
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


# ==================== ЗАПУСК ====================

async def main():
    dp = Dispatcher(storage=storage)
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info(f"Бот запущен (polling), ADMIN_ID={ADMIN_ID}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
