import asyncio
from datetime import datetime
from typing import Union
import pytz
from db.models.notifications import Notifications
from db.repository import notifications_repository


class NotificationSchedulerError(Exception):
    """Исключение для ошибок планирования уведомления."""
    pass


class NotificationLimitError(Exception):
    """Исключение для превышения лимита уведомлений."""
    pass


async def schedule_notification(
    when_send_str: str,
    user_id: int,
    text_notification: str,
    *,
    fmt: str = "%Y-%m-%d %H:%M:%S"
) -> bool:
    # Проверяем количество активных уведомлений пользователя
    active_notifications = await notifications_repository.get_active_notifications_by_user_id(user_id)
    if len(active_notifications) >= 10:
        raise NotificationLimitError(
            f"Превышен лимит уведомлений. У вас уже есть {len(active_notifications)} активных уведомлений. "
            "Максимальное количество: 10. Дождитесь срабатывания существующих уведомлений "
        )

    try:
        when_send = datetime.strptime(when_send_str, fmt)
    except ValueError as e:
        raise NotificationSchedulerError(
            f"Неверный формат даты/времени: {when_send_str!r}. "
            f"Ожидается формат {fmt}"
        ) from e

    # Проверка на разумные пределы дат
    if when_send.year > 2030:
        raise NotificationSchedulerError(
            f"Дата слишком далекая: {when_send.year}. Максимум до 2030 года."
        )
    
    if when_send.year < 2024:
        raise NotificationSchedulerError(
            f"Дата в прошлом: {when_send.year}."
        )

    # Получаем текущее московское время для сравнения
    moscow_tz = pytz.timezone('Europe/Moscow')
    utc_now = datetime.utcnow()
    moscow_now = utc_now.replace(tzinfo=pytz.UTC).astimezone(moscow_tz)
    # Убираем timezone info для сравнения с naive datetime
    moscow_now_naive = moscow_now.replace(tzinfo=None)
    
    if when_send <= moscow_now_naive:
        raise NotificationSchedulerError(
            f"Нельзя запланировать уведомление на прошлое время. "
            f"Указанное время: {when_send}, текущее московское время: {moscow_now_naive.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    # Проверка длины текста уведомления  
    if len(text_notification.strip()) < 3:
        raise NotificationSchedulerError(
            "Текст уведомления слишком короткий. Минимум 3 символа."
        )
    
    if len(text_notification) > 500:
        raise NotificationSchedulerError(
            "Текст уведомления слишком длинный. Максимум 500 символов."
        )

    success = await notifications_repository.add_notification(
        when_send=when_send,
        user_id=user_id,
        text_notification=text_notification
    )
    return success