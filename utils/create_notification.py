import asyncio
from datetime import datetime
from typing import Union
import pytz
from db.models.notifications import Notifications
from db.repository import notifications_repository


class NotificationBaseError(Exception):
    """Базовое исключение для всех ошибок уведомлений."""
    pass


class NotificationFormatError(NotificationBaseError):
    """Исключение для неверного формата даты/времени."""
    pass


class NotificationDateTooFarError(NotificationBaseError):
    """Исключение для слишком далекой даты (после 2030 года)."""
    pass


class NotificationDateInPastError(NotificationBaseError):
    """Исключение для даты в прошлом."""
    pass


class NotificationPastTimeError(NotificationBaseError):
    """Исключение для времени в прошлом."""
    pass


class NotificationTextTooShortError(NotificationBaseError):
    """Исключение для слишком короткого текста уведомления."""
    pass


class NotificationTextTooLongError(NotificationBaseError):
    """Исключение для слишком длинного текста уведомления."""
    pass


class NotificationLimitError(NotificationBaseError):
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
        raise NotificationFormatError(
            f"Неверный формат даты/времени: {when_send_str!r}. "
            f"Ожидается формат {fmt}, например: '2024-12-25 15:30:00'"
        ) from e

    # Проверка на разумные пределы дат
    if when_send.year > 2030:
        raise NotificationDateTooFarError(
            f"Дата слишком далекая: {when_send.year} год. "
            "Можно устанавливать уведомления максимум до 2030 года."
        )
    
    if when_send.year < 2024:
        raise NotificationDateInPastError(
            f"Указанный год ({when_send.year}) уже прошел. "
            "Укажите дату в будущем."
        )

    # Получаем текущее московское время для сравнения
    moscow_tz = pytz.timezone('Europe/Moscow')
    utc_now = datetime.utcnow()
    moscow_now = utc_now.replace(tzinfo=pytz.UTC).astimezone(moscow_tz)
    # Убираем timezone info для сравнения с naive datetime
    moscow_now_naive = moscow_now.replace(tzinfo=None)
    
    if when_send <= moscow_now_naive:
        raise NotificationPastTimeError(
            f"Указанное время уже прошло. "
            f"Вы указали: {when_send.strftime('%d.%m.%Y в %H:%M')}, "
            f"а сейчас: {moscow_now_naive.strftime('%d.%m.%Y в %H:%M')} (московское время). "
            "Укажите время в будущем."
        )

    # Проверка длины текста уведомления  
    if len(text_notification.strip()) < 3:
        raise NotificationTextTooShortError(
            "Текст уведомления слишком короткий. "
            "Напишите хотя бы 3 символа, чтобы напоминание было понятным."
        )
    
    if len(text_notification) > 500:
        raise NotificationTextTooLongError(
            f"Текст уведомления слишком длинный ({len(text_notification)} символов). "
            "Максимум 500 символов. Сократите текст."
        )

    success = await notifications_repository.add_notification(
        when_send=when_send,
        user_id=user_id,
        text_notification=text_notification
    )
    return success