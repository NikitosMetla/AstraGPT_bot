import asyncio
import datetime
import traceback

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db.repository import users_repository, notifications_repository


scheduler: AsyncIOScheduler | None = None


async def safe_send_notif(bot: Bot):
    from bot import logger
    """
    Вокруг send_notif — своя зона try/except.
    Любая ошибка там отлавливается и логируется, но планировщик продолжит жить.
    """
    try:
        await send_notif(bot)
    except Exception:
        logger.exception("Ошибка в send_notif")

def job_error_listener(event):
    from bot import logger
    """
    Листенер для ошибок внутри задач.
    """
    logger.error(f"Job {event.job_id} failed: {event.exception}")

async def monitor_scheduler():
    from bot import logger
    """
    Периодически проверяем, что scheduler.running==True, иначе перезапускаем.
    """
    global scheduler
    while True:
        await asyncio.sleep(300)  # проверять каждые 10 секунд
        if scheduler and not scheduler.running:
            logger.warning("Scheduler is not running — перезапускаем")
            try:
                scheduler.start()
            except Exception:
                logger.exception("Не удалось перезапустить scheduler")


async def send_notif(bot: Bot):
    # users = await users_repository.select_all_users()
    time_now = datetime.datetime.now()
    # print(time_now)
    notifications = await notifications_repository.select_all_active_notifications()
    for notif in notifications:
        try:
            if (time_now.date() == notif.when_send.date() and time_now.time().hour + 3 == notif.when_send.time().hour and time_now.time().minute == notif.when_send.time().minute) or notif.when_send < time_now:
                await bot.send_message(chat_id=notif.user_id, text="<b>Напоминание:</b>\n\n" + notif.text_notification)
                await notifications_repository.update_active_by_notification_id(notification_id=notif.id)
        except:
            print(traceback.format_exc())
            continue