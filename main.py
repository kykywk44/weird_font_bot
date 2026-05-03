import asyncio
import json
import logging
import os
from pathlib import Path
from aiohttp import web

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (Message, CallbackQuery, FSInputFile, 
                           InlineKeyboardMarkup, InlineKeyboardButton, 
                           LinkPreviewOptions, MessageEntity)

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

ADMIN_ID = int(os.getenv("ADMIN_ID", "855323286"))
FONT_FILE_NAME = os.getenv("FONT_FILE_NAME", "font.ttf")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") # Например: https://weird-font-bot.onrender.com

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

# Инициализация
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()

USERS_DB_FILE = "users.json"
SETTINGS_FILE = "settings.json"

class AdminState(StatesGroup):
    waiting_for_welcome_text = State()

# ==================== БАЗА ДАННЫХ И НАСТРОЙКИ ====================

def load_json(filename, default_factory):
    if not os.path.exists(filename):
        return default_factory()
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки {filename}: {e}")
        return default_factory()

def save_json(filename, data):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения {filename}: {e}")

def entities_to_html(text: str, entities: list) -> str:
    """Конвертирует форматирование Telegram в HTML строку"""
    if not entities:
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    positions = set([0, len(text)])
    for e in entities:
        positions.add(max(0, e.offset))
        positions.add(max(0, min(e.offset + e.length, len(text))))
    
    sorted_positions = sorted(list(positions))
    tag_priority = {'bold': 0, 'italic': 1, 'underline': 2, 'strikethrough': 3, 'code': 4, 'pre': 5, 'text_link': 7}

    def open_tag(e):
        tags = {'bold': '<b>', 'italic': '<i>', 'underline': '<u>', 'strikethrough': '<s>', 'code': '<code>', 'pre': '<pre>'}
        if e.type in tags: return tags[e.type]
        if e.type == 'text_link': return f'<a href="{e.url}">'
        return ''

    def close_tag(e):
        tags = {'bold': '</b>', 'italic': '</i>', 'underline': '</u>', 'strikethrough': '</s>', 'code': '</code>', 'pre': '</pre>', 'text_link': '</a>'}
        return tags.get(e.type, '')

    result = []
    for i in range(len(sorted_positions) - 1):
        start, end = sorted_positions[i], sorted_positions[i+1]
        covering = [e for e in entities if e.offset <= start and (e.offset + e.length) >= end]
        covering.sort(key=lambda e: tag_priority.get(e.type, 99))
        
        for e in covering: result.append(open_tag(e))
        result.append(text[start:end].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
        for e in reversed(covering): result.append(close_tag(e))
    
    return ''.join(result)

# ==================== ОБРАБОТЧИКИ ====================

@router.message(Command("start"))
async def cmd_start(message: Message):
    db = load_json(USERS_DB_FILE, dict)
    user_id = str(message.from_user.id)
    if user_id not in db:
        db[user_id] = {"username": message.from_user.username, "first_name": message.from_user.first_name}
        save_json(USERS_DB_FILE, db)
        logger.info(f"Новый пользователь: {user_id}")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Я ознакомлен и согласен", callback_data="accept_license")]])
    settings = load_json(SETTINGS_FILE, lambda: {"welcome_text": None})
    
    text = settings.get("welcome_text") or "Привет! Ознакомьтесь с лицензией перед скачиванием шрифта."
    await message.answer(text, reply_markup=keyboard, link_preview_options=LinkPreviewOptions(is_disabled=True))

@router.callback_query(F.data == "accept_license")
async def accept_license(callback: CallbackQuery):
    font_path = Path(FONT_FILE_NAME)
    if font_path.exists():
        await callback.message.answer_document(FSInputFile(FONT_FILE_NAME), caption="Ваш файл шрифта.")
    else:
        await callback.message.answer("Файл шрифта временно недоступен. Свяжитесь с @bykvv")
    await callback.answer()

@router.message(Command("setwelcome"))
async def cmd_setwelcome(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("Отправьте текст нового приветствия с любым форматированием:")
    await state.set_state(AdminState.waiting_for_welcome_text)

@router.message(AdminState.waiting_for_welcome_text)
async def process_welcome_text(message: Message, state: FSMContext):
    html = entities_to_html(message.text, message.entities) if message.entities else message.text
    save_json(SETTINGS_FILE, {"welcome_text": html})
    await message.answer("✅ Приветствие обновлено!")
    await state.clear()

# ==================== WEBHOOK & SERVER ====================

async def on_startup(bot: Bot):
    if WEBHOOK_URL:
        await bot.set_webhook(f"{WEBHOOK_URL}/webhook", drop_pending_updates=True)
        logger.info(f"Вебхук установлен: {WEBHOOK_URL}/webhook")

async def handle_webhook(request):
    try:
        update = await request.json()
        await dp.feed_webhook_update(bot, update)
    except Exception as e:
        logger.error(f"Ошибка вебхука: {e}")
    return web.Response(text="OK")

async def handle_health(request):
    return web.Response(text="OK")

app = web.Application()
app.router.add_post("/webhook", handle_webhook)
app.router.add_get("/", handle_health)

async def main():
    dp.include_router(router)
    dp.startup.register(on_startup)
    
    port = int(os.getenv("PORT", 8000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    
    logger.info(f"Запуск на порту {port}")
    await site.start()
    
    # Держим цикл активным
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановка")
