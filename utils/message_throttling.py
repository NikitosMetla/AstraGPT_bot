import asyncio
import time
import traceback
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, TelegramObject

from db.repository import users_repository, admin_repository, events_repository, subscriptions_repository
from settings import MESSAGE_SPAM_TIMING
from bot import logger


class CombinedMiddleware(BaseMiddleware):
    """
    Объединенная middleware для проверки спама сообщений и логирования событий пользователя в базу данных.

    ✅ Новое в версии 2025‑06‑11
        • Не учитываются повторные сообщения с тем же `media_group_id` (альбомы фото/документов).
        • Убрано блокирующее `await asyncio.sleep()`; разблокировка происходит в фоне через `asyncio.create_task`.
    """

    def __init__(self, debug: bool = False):
        self.storage: Dict[int, Dict[str, Any]] = {}
        self.debug = debug
        self.events_repo = events_repository
        if self.debug:
            print("CombinedMiddleware initialized with debugging enabled.")

    # ---------------------------------------------------------------------
    # Вспомогательные методы
    # ---------------------------------------------------------------------

    def log(self, message: str) -> None:
        if self.debug:
            print(message)

    async def _unblock_later(self, user_id: int) -> None:
        """Снимает флаг `spam_block` по истечении `MESSAGE_SPAM_TIMING`."""
        await asyncio.sleep(MESSAGE_SPAM_TIMING)
        if user_id in self.storage:
            self.storage[user_id]["spam_block"] = False
            self.log(f"Spam block lifted for user_id={user_id}")

    # ---------------------------------------------------------------------
    # Основной вызов middleware
    # ---------------------------------------------------------------------

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user_id: Optional[int] = None
        media_gid: Optional[str] = None

        try:
            # ------------------ Определяем user_id и media_group_id ------------------
            if isinstance(event, Message):
                user_id = event.from_user.id
                media_gid = event.media_group_id
            elif isinstance(event, CallbackQuery):
                user_id = event.from_user.id
            elif hasattr(event, "from_user") and event.from_user:
                user_id = event.from_user.id

            # ----------------------- Анти‑спам‑фильтр -----------------------
            if isinstance(event, Message) and user_id:
                # Загружаем данные пользователя из БД
                user_data = await users_repository.get_user_by_user_id(user_id=user_id)
                data["user_data"] = user_data

                # Регистрация нового пользователя
                if not user_data:
                    await event.answer(
                        "Привет! Я твой универсальный помощник - AstraGPT. Вместе со мной можно общаться, "
                        "учиться, создавать картинки и еще очень много всего. Просто опиши задачу и я сделаю все в лучшем виде! 🚀"
                    )
                    await asyncio.sleep(1)
                    await users_repository.add_user(user_id=user_id, username=event.from_user.username)
                    logger.log("JOIN", f"{user_id} | @{event.from_user.username}")
                    self.log(f"New user registered: user_id={user_id}, username=@{event.from_user.username}")
                # user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
                # if user_sub is None:
                #     await subscriptions_repository.add_subscription(type_sub_id=2, user_id=user_id,
                #                                                     photo_generations=3, time_limit_subscription=30)
                # Предыдущее состояние пользователя в хранилище
                check = self.storage.get(user_id)

                # ➊ Пропускаем повторные сообщения той же медиагруппы -----------------
                if media_gid and check and check.get("media_group_id") == media_gid:
                    # Обновляем только timestamp и сразу передаем управление хендлеру
                    self.storage[user_id]["timestamp"] = time.time()
                    self.log(f"Message skipped spam‑check (same media_group_id) for user_id={user_id}")
                    return await handler(event, data)
                #
                # ➋ Базовая анти‑спам‑логика -----------------------------------------
                if check:
                    # Уже активен блок? — игнорируем
                    if check["spam_block"]:
                        self.log(f"Spam block active for user_id={user_id}, ignoring message.")
                        return

                    # Проверяем интервал
                    if time.time() - check["timestamp"] <= MESSAGE_SPAM_TIMING:
                        self.storage[user_id]["timestamp"] = time.time()
                        self.storage[user_id]["spam_block"] = True
                        await event.answer(
                            "<b>Давай помедленнее, не успеваю обработать все запросы 🫠</b>",
                            parse_mode=ParseMode.HTML
                        )
                        logger.log("SPAM", f"{user_id} | @{event.from_user.username}")
                        self.log(f"Spam detected for user_id={user_id}, blocking temporarily.")

                        # Снимаем блокировку асинхронно, чтобы не тормозить pipeline
                        asyncio.create_task(self._unblock_later(user_id))
                        return

                # ➌ Обновляем / создаём запись пользователя в хранилище --------------
                self.storage[user_id] = {
                    "timestamp": time.time(),
                    "spam_block": False,
                    "media_group_id": media_gid,  # может быть None
                }
                self.log(f"Updated storage for user_id={user_id}: {self.storage[user_id]}")

            # -------------------------- Логирование события --------------------------
            if user_id:
                event_type: Optional[str] = None
                if isinstance(event, Message):
                    if event.text:
                        event_type = "message_text"
                    elif event.photo:
                        event_type = "message_photo"
                    elif event.document:
                        event_type = "message_document"
                    elif event.voice:
                        event_type = "message_voice"
                    else:
                        event_type = "message_other"
                elif isinstance(event, CallbackQuery):
                    event_type = "callback_query"
                else:
                    event_type = f"event_{event.__class__.__name__}"

                # Пишем событие в БД
                user = await users_repository.get_user_by_user_id(user_id=user_id)
                if user and event_type:
                    await self.events_repo.add_event(user_id=user_id, event_type=event_type)

            # Передаём управление следующему хендлеру --------------------------------
            return await handler(event, data)

        except Exception as e:
            # Общий обработчик ошибок
            self.log(f"Error in CombinedMiddleware for user_id={user_id}: {e}")
            logger.log(
                "ERROR_HANDLER",
                f"{user_id} | Ошибка в CombinedMiddleware: {traceback.format_exc()}"
            )

        finally:
            if user_id:
                self.log(f"Final storage state for user_id={user_id}: {self.storage.get(user_id)}")
