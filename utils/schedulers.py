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

import asyncio
import traceback
# from datetime import datetime
from apscheduler.events import (
    EVENT_JOB_EXECUTED,
    EVENT_JOB_ERROR,
    EVENT_JOB_MISSED,
    EVENT_SCHEDULER_SHUTDOWN,
    EVENT_SCHEDULER_PAUSED,
    JobExecutionEvent
)


def job_error_listener(event: JobExecutionEvent):
    """Обработка ошибок в задачах"""
    from settings import logger

    error_msg = f"Job '{event.job_id}' failed with exception:\n{event.exception}\n{event.traceback}"
    logger.log("SCHEDULER_ERROR", error_msg)

    # Опционально: уведомление админов о критических ошибках
    # asyncio.create_task(notify_admins_about_error(event))


def scheduler_shutdown_listener(event):
    """Обработка остановки планировщика"""
    from settings import logger
    logger.log("SCHEDULER_ERROR", f"Scheduler shutdown at {datetime.now()}")


def scheduler_paused_listener(event):
    """Обработка паузы планировщика"""
    from settings import logger
    logger.log("SCHEDULER_ERROR", f"Scheduler paused at {datetime.now()}")


async def monitor_scheduler():
    """
    Мониторинг работы планировщика
    """
    from settings import logger

    while True:
        try:
            await asyncio.sleep(3600)  # Каждый час
        except Exception as e:
            logger.log("SCHEDULER_ERROR", f"Monitor error: {traceback.format_exc()}")


async def safe_send_notif(bot: Bot):
    from settings import logger
    """
    Вокруг send_notif — своя зона try/except.
    Любая ошибка там отлавливается и логируется, но планировщик продолжит жить.
    """
    try:
        await send_notif(bot)
    except Exception:
        logger.exception("Ошибка в send_notif")


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


async def safe_extend_users_sub(main_bot: Bot):
    from settings import logger
    try:
        await extend_users_sub(main_bot=main_bot)
    except:
        logger.log("SCHEDULER_ERROR", f"safe_extend_users_sub error: {traceback.format_exc()}")

#
async def extend_users_sub(main_bot: Bot):
    from settings import logger
    users_subs = await subscriptions_repository.select_all_active_subscriptions()
    now_datetime = datetime.datetime.now()
    extended_subs = 0
    extended_free_subs = 0
    for sub in users_subs:
        if (sub.last_billing_date + datetime.timedelta(days=sub.time_limit_subscription)) <= now_datetime:
            type_sub = await type_subscriptions_repository.get_type_subscription_by_id(type_id=sub.type_subscription_id)
            if sub is not None and sub.is_paid_sub:
                try:
                    if sub.method_id is None:
                        await subscriptions_repository.deactivate_subscription(subscription_id=sub.id)
                        await main_bot.send_message(chat_id=sub.user_id,
                                                    text="Дорогой друг, не получилось автоматически продлить твою подписку."
                                                     " Если ты видишь, что при этом у тебя"
                                                     " списались деньги - обязательно пиши нашу поддержку по команде /support")
                        continue

                    payment = create_recurring_payment(method_id=sub.method_id,
                                                      amount=type_sub.price)
                    if payment.status == 'succeeded':
                        # try:
                        max_generations = type_sub.max_generations
                        await subscriptions_repository.replace_subscription(subscription_id=sub.id,
                                                                            user_id=sub.user_id,
                                                                            time_limit_subscription=30,
                                                                            active=True,
                                                                            type_sub_id=type_sub.id,
                                                                            method_id=sub.method_id,
                                                                            photo_generations=max_generations,
                                                                            video_generations=type_sub.max_video_generations)

                        await main_bot.send_message(chat_id=sub.user_id,
                                                    text="🚀Дорогой друг, твоя подписка автоматически продлена на один месяц")
                        extended_subs += 1
                    else:
                        logger.log("EXTEND_SUB_ERROR", f"payment_data - {payment.json()}")
                        await main_bot.send_message(chat_id=sub.user_id,
                                                    text="Дорогой друг, не получилось автоматически продлить твою подписку."
                                                         " Если ты видишь, что при этом у тебя"
                                                         " списались деньги - обязательно пиши нашу поддержку по команде /support")
                except:
                    logger.log("EXTEND_SUB_ERROR", traceback.format_exc())
                    await main_bot.send_message(chat_id=sub.user_id,
                                                text="Дорогой друг, не получилось автоматически продлить твою подписку."
                                                     " Если ты видишь, что при этом у тебя"
                                                     " списались деньги - обязательно пиши нашу поддержку по команде /support")
            else:
                try:
                    if sub is not None:
                        await subscriptions_repository.update_time_limit_subscription(subscription_id=sub.id, new_time_limit=30)
                        extended_free_subs += 1
                except:
                    logger.log("EXTEND_SUB_ERROR", traceback.format_exc())
    logger.log("SCHEDULER_INFO",
               f"🚀SCHEDULER extended_subs - {extended_subs} | extended_free_subs - {extended_free_subs}")

