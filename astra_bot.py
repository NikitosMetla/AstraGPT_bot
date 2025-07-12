import asyncio
import datetime
import ssl
from pathlib import Path

from aiogram import Dispatcher, Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update, InputFile, BufferedInputFile
from aiogram.methods import SetWebhook, DeleteWebhook
from aiohttp import web
from loguru import logger

from db.engine import DatabaseEngine
from handlers.user_handler import standard_router
from settings import storage_bot, token_design_level
from utils.message_throttling import MessageSpamMiddleware

# 1. Параметры вебхука:
WEBHOOK_HOST = "https://92.51.37.55"  # Ваш публичный IP или доменное имя
WEBHOOK_PATH = "/webhook"            # Путь, под который nginx проксирует запросы на aiohttp {{proxy_pass}}
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"  # Полный URL для Telegram

# 2. Пути до SSL-файлов:
#   - certificate.crt (публичная часть), которую отправляем Telegram при self-signed
#   - private.key (приватный ключ) используется локально для aiohttp
SSL_CERT_PATH = "/etc/ssl/certs/certificate.crt"
SSL_PRIV_PATH = "/etc/ssl/private/private.key"

# 3. Создаём экземпляр Bot и Dispatcher (без изменений):
main_bot = Bot(token=token_design_level, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=storage_bot)

async def on_startup(app: web.Application):
    # 3.1. Удаляем существующий вебхук (на случай, если бот до этого работал в polling):
    await main_bot.delete_webhook(drop_pending_updates=True)
    # 3.2. Устанавливаем новый вебхук (передаём файл сертификата для self-signed):
    await main_bot.set_webhook(
        url=WEBHOOK_URL,
        certificate=BufferedInputFile.from_file(SSL_CERT_PATH)
    )


async def on_shutdown(app: web.Application):
    # 3.3. При завершении сервиса удаляем вебхук, чтобы Telegram перестал шлать запросы
    await main_bot.delete_webhook()

@dp.message()  # 3.4. Регистрируем ваши хендлеры, как и раньше
async def handle_message(message):
    # Здесь можно распределять сообщения через routers, если у вас уже подключён standard_router
    # Например:
    # await message.answer("Бот работает через вебхук")
    pass

async def handle_updates(request: web.Request):
    update = Update(**await request.json())
    await dp.feed_update(main_bot, update)   # <-- правильный метод
    return web.Response(text="OK")


async def setup_bot():
    # 3.6. Инициализация логирования и подключения к базе — почти без изменений:
    logger.add(f"logs/{datetime.date.today()}.log",
               format="{time:DD-MMM-YYYY HH:mm:ss} | {level:^25} | {message}",
               enqueue=True, rotation="00:00")
    logger.level("JOIN", no=60, color="<green>")
    logger.level("SPAM", no=60, color="<yellow>")
    logger.level("ERROR_HANDLER", no=60, color="<red>")

    db_engine = DatabaseEngine()
    await db_engine.proceed_schemas()
    dp.message.middleware.register(MessageSpamMiddleware())
    dp.include_routers(standard_router)
    # 3.7. Вместо polling мы настраиваем aiohttp-приложение с вебхуком
    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    app.router.add_post(WEBHOOK_PATH, handle_updates)  # Роут для POST /webhook

    # 3.8. SSL-контекст для aiohttp. Он слушает на localhost:8443 и ожидает HTTPS-соединений
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(SSL_CERT_PATH, SSL_PRIV_PATH)

    # 3.9. Запускаем aiohttp-сервер локально на 127.0.0.1:8443
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8443, ssl_context=ssl_context)
    await site.start()

    print(f"Бот запущен на вебхуке: {WEBHOOK_URL}")

async def main():
    await setup_bot()
    # 3.10. Чтобы процесс не завершается, ставим вечное ожидание
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
