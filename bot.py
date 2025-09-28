import asyncio
import datetime

from aiogram import Dispatcher, Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.events import EVENT_JOB_ERROR, EVENT_SCHEDULER_SHUTDOWN

from db.engine import DatabaseEngine
from handlers.payment_handler import payment_router
from handlers.user_handler import standard_router
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from settings import (
    storage_bot, main_bot_token, set_current_bot, set_current_assistant, 
    initialize_logger, set_current_loop, logger
)
from utils.schedulers import send_notif, safe_send_notif, job_error_listener, scheduler, monitor_scheduler


main_bot = Bot(token=main_bot_token,
               default=DefaultBotProperties(parse_mode=ParseMode.HTML))



async def main():
    set_current_bot(main_bot)
    from utils.combined_gpt_tools import GPT
    set_current_assistant(GPT())
    set_current_loop(asyncio.get_running_loop())
    
    # Инициализируем logger с настройками для основного бота
    initialize_logger()

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
        logger.log("STOPPED", "‼️ MAIN Bot has STOPPED")

        # 2. Дополнительно вручную роняем рассылку «STOPPED» по админам,
        #    чтобы не зависеть от очередей Loguru
        from bot_admin import admin_bot

        time_str = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
        text = (
            f"<b>{time_str}</b>\n"
            f"<b>Level:</b> STOPPED\n"
            "‼️ MAIN Bot has STOPPED"
        )
        from db.repository import admin_repository
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
