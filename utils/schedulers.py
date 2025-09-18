import asyncio
import datetime
import traceback
import pytz

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db.repository import users_repository, notifications_repository, subscriptions_repository, \
    type_subscriptions_repository
from utils.payment_for_services import create_recurring_payment

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
    # Получаем московское время
    moscow_tz = pytz.timezone('Europe/Moscow')
    utc_now = datetime.datetime.utcnow()
    moscow_now = utc_now.replace(tzinfo=pytz.UTC).astimezone(moscow_tz)
    
    # Убираем timezone info для сравнения с naive datetime из БД
    moscow_now_naive = moscow_now.replace(tzinfo=None)
    
    notifications = await notifications_repository.select_all_active_notifications()
    for notif in notifications:
        try:
            # Предполагаем, что notif.when_send хранится как московское время (naive datetime)
            # Проверяем, наступило ли время для отправки уведомления
            if moscow_now_naive >= notif.when_send:
                await bot.send_message(chat_id=notif.user_id, text="<b>🚨Напоминание:</b>\n\n" + notif.text_notification)
                await notifications_repository.update_active_by_notification_id(notification_id=notif.id)
        except Exception:
            print(traceback.format_exc())
            continue


#
async def extend_users_sub(main_bot: Bot):
    from bot import logger
    users_subs = await subscriptions_repository.select_all_active_subscriptions()
    now_datetime = datetime.datetime.now()
    for sub in users_subs:
        type_sub = await type_subscriptions_repository.get_type_subscription_by_id(type_id=sub.type_subscription_id)
        if sub is not None and type_sub.plan_name != "Free":
            try:
                if sub.method_id is None:
                    await subscriptions_repository.deactivate_subscription(subscription_id=sub.id)
                    await main_bot.send_message(chat_id=sub.user_id,
                                                text="Дорогой друг, не получилось автоматически продлить твою подписку."
                                                     " Если ты видишь, что при этом у тебя"
                                                     " списались деньги - обязательно пиши нашу поддержку @sozdav_ai")
                    continue

                result = create_recurring_payment(method_id=sub.method_id,
                                                  amount=type_sub.price)
                if result:
                    # try:
                    max_generations = type_sub.max_generations
                    await subscriptions_repository.replace_subscription(subscription_id=sub.id,
                                                                        user_id=sub.user_id,
                                                                        time_limit_subscription=30,
                                                                        active=True,
                                                                        type_sub_id=type_sub.id,
                                                                        method_id=sub.method_id,
                                                                        photo_generations=max_generations)

                    await main_bot.send_message(chat_id=sub.user_id,
                                                text="Дорогой друг, твоя подписка автоматически продлена на один месяц")
            except:
                logger.log("EXTEND_SUB_ERROR", traceback.format_exc())
                await main_bot.send_message(chat_id=sub.user_id,
                                            text="Дорогой друг, не получилось автоматически продлить твою подписку."
                                                 " Если ты видишь, что при этом у тебя"
                                                 " списались деньги - обязательно пиши нашу поддержку по команде /support")