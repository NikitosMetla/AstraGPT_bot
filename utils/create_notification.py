import asyncio
from datetime import datetime
from typing import Union
from db.models.notifications import Notifications
from db.repository import notifications_repository


class NotificationSchedulerError(Exception):
    """Исключение для ошибок планирования уведомления."""
    pass


async def schedule_notification(
    when_send_str: str,
    user_id: int,
    text_notification: str,
    *,
    fmt: str = "%Y-%m-%d %H:%M:%S"
) -> bool:
    try:
        when_send = datetime.strptime(when_send_str, fmt)
    except ValueError as e:
        raise NotificationSchedulerError(
            f"Неверный формат даты/времени: {when_send_str!r}. "
            f"Ожидается формат {fmt}"
        ) from e

    now = datetime.now()
    if when_send < now:
        raise NotificationSchedulerError(
            f"Нельзя запланировать уведомление на прошлое время: {when_send} < {now}"
        )

    success = await notifications_repository.add_notification(
        when_send=when_send,
        user_id=user_id,
        text_notification=text_notification
    )
    return