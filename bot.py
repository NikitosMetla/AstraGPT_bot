import asyncio
import datetime
import traceback

from aiogram import Dispatcher, Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.events import EVENT_JOB_ERROR, EVENT_SCHEDULER_SHUTDOWN
from loguru import logger


from db.engine import DatabaseEngine
from db.repository import admin_repository
from handlers.payment_handler import payment_router
from handlers.user_handler import standard_router
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from settings import storage_bot, main_bot_token, set_current_bot, set_current_assistant
from utils.schedulers import send_notif, safe_send_notif, job_error_listener, scheduler, monitor_scheduler


main_bot = Bot(token=main_bot_token,
               default=DefaultBotProperties(parse_mode=ParseMode.HTML))


# глобальная переменная для хранения основного event loop
_loop: asyncio.AbstractEventLoop | None = None

async def telegram_admin_sink(message):
    from bot_admin import admin_bot
    """
    Фоновые оповещения админам — полностью асинхронно.
    """
    try:
        record = message.record
        time = record["time"].strftime("%d-%b-%Y %H:%M:%S")
        level = record["level"].name
        text = f"<b>{time}</b>\n<b>Level:</b> {level}\n{record['message']}"
        admins = await admin_repository.select_all_admins()
        for admin in admins:
            try:
                print(admin.admin_id)
                await admin_bot.send_message(chat_id=admin.admin_id, text=text)
            except:
                print(traceback.format_exc())
                continue
    except Exception:
        logger.exception("Ошибка внутри telegram_admin_sink")

def loguru_sink_wrapper(message):
    """
    Синхронный синк для Loguru: из любого треда шлёт корутину в наш loop.
    """
    if _loop:
        asyncio.run_coroutine_threadsafe(telegram_admin_sink(message), _loop)
    else:
        logger.error("Event loop is not initialized, cannot notify admins")

async def main():
    set_current_bot(main_bot)
    from utils.combined_gpt_tools import GPT
    set_current_assistant(GPT())
    global _loop
    _loop = asyncio.get_running_loop()
    from datetime import datetime
    # Файловый лог и уровни
    logger.add(f"logs/{datetime.now().strftime('%d-%b-%Y %H:%M:%S')}.log",
               format="{time:DD-MMM-YYYY HH:mm:ss} | {level:^25} | {message}",
               enqueue=True, rotation="00:00")
    logger.level("JOIN", no=60, color="<green>")
    logger.level("SPAM", no=60, color="<yellow>")
    logger.level("START_BOT", no=25, color="<blue>")
    logger.level("STOPPED", no=25, color="<blue>")
    logger.level("ERROR_HANDLER", no=60, color="<red>")
    logger.level("GPT_ERROR", no=65, color="<red>")
    logger.level("EXTEND_SUB_ERROR", no=65, color="<red>")
    # … другие уровни …

    # Синк для START_BOT
    logger.add(
        loguru_sink_wrapper,
        level="START_BOT",
        filter=lambda rec: rec["level"].name == "START_BOT",
        enqueue=True,
    )
    # Синк для ERROR_HANDLER, GPT_ERROR, STOPPED и т.д.
    for lvl in ("ERROR_HANDLER", "GPT_ERROR"):
        logger.add(
            loguru_sink_wrapper,
            level=lvl,
            filter=lambda rec, L=lvl: rec["level"].name == L,
            enqueue=True,
        )

    # Лог о старте
    logger.log("START_BOT", "🚀 Bot was STARTED")

    # Инициализация БД, диспетчера и т. д.
    db_engine = DatabaseEngine()
    await db_engine.proceed_schemas()
    await main_bot.delete_webhook(drop_pending_updates=True)

    dp = Dispatcher(storage=storage_bot)
    from utils.message_throttling import CombinedMiddleware
    dp.message.middleware.register(CombinedMiddleware())
    dp.include_routers(payment_router, standard_router)

    scheduler = AsyncIOScheduler()
    # заменяем send_notif на safe_send_notif
    scheduler.add_job(
        func=safe_send_notif,
        args=[main_bot],
        trigger="cron",
        second=0,
        max_instances=20,
        misfire_grace_time=120
    )
    # Листенер ошибок в задачах
    scheduler.add_listener(job_error_listener, EVENT_JOB_ERROR)
    # Листенер неожиданного shutdown
    scheduler.add_listener(lambda e: logger.warning("Scheduler shutdown"), EVENT_SCHEDULER_SHUTDOWN)
    scheduler.start()

    # Запускаем корутину-монитор
    asyncio.create_task(monitor_scheduler())
    try:
    # Запуск polling
        await dp.start_polling(main_bot, polling_timeout=3, skip_updates=False)
    finally:
    # Лог о завершении и уведомление админам
        logger.log("STOPPED", "‼️ Bot has STOPPED")

        # 2. Дополнительно вручную роняем рассылку «STOPPED» по админам,
        #    чтобы не зависеть от очередей Loguru
        from bot_admin import admin_bot

        time_str = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
        text = (
            f"<b>{time_str}</b>\n"
            f"<b>Level:</b> STOPPED\n"
            "‼️ Bot has STOPPED"
        )
        admins = await admin_repository.select_all_admins()
        for admin in admins:
            try:
                await admin_bot.send_message(chat_id=admin.admin_id, text=text)
            except Exception:
                # просто игнорируем, чтобы не мешало остальным
                pass

        # 3. Останавливаем планировщик
        if scheduler:
            scheduler.shutdown(wait=False)

        # 4. Даем секунду «на отлёт» всем оставшимся корутинам, если нужно
        await asyncio.sleep(1)

        # 5. Закрываем хранилище и сессию
        await storage_bot.close()
        await main_bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
