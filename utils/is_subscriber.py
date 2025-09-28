import contextlib
import time
import traceback
from functools import wraps
from typing import Optional

from aiogram.fsm.context import FSMContext

from aiogram import types, Bot

from data.keyboards import subscriptions_keyboard, channel_sub_keyboard
from db.repository import admin_repository, subscriptions_repository, type_subscriptions_repository
from settings import sub_text, sozdavai_channel_id, no_subscriber_message



def is_subscriber(func):
    from settings import logger
    @wraps(func)
    async def wrapper(message: types.Message | types.CallbackQuery, state: FSMContext, bot: Bot, **kwargs):
        # print("========================= " + func.__name__ + " ============================")
        # return await func(message, state, bot, **kwargs)
        try:
            user_sub = await subscriptions_repository.get_active_subscription_by_user_id(message.from_user.id)
            type_sub = await type_subscriptions_repository.get_type_subscription_by_id(type_id=user_sub.type_subscription_id)
            print(type_sub.plan_name)
            print(user_sub)
            if user_sub and type_sub.plan_name != "Free":
                # print('Проверка на подписку пройдена')
                return await func(message, state, bot, **kwargs)
            elif type(message) == types.Message:
                # await message.delete()
                sub_types = await type_subscriptions_repository.select_all_type_subscriptions()
                await message.answer("🚨К сожалению, данная функция, которую ты"
                                     " пытаешься использовать, доступна только по подписке\n\n" + sub_text,
                                     reply_markup=subscriptions_keyboard(sub_types).as_markup())
            else:
                try:
                    await message.message.delete()
                finally:
                    sub_types = await type_subscriptions_repository.select_all_type_subscriptions()
                    await message.message.answer("🚨К сожалению, данная функция, которую ты пытаешься"
                                                 " использовать доступна только по подписке\n\n" + sub_text,
                                         reply_markup=subscriptions_keyboard(sub_types).as_markup())
        except Exception:
            logger.log("ERROR_HANDLER", f"is_channel_subscriber\n\n{traceback.format_exc()}")
            pass
    return wrapper


# простая дедупликация показов по одному альбому
_seen_media_groups: dict[int, float] = {}  # {media_group_id: ts}

def _find_in_args_kwargs(args, kwargs, cls):
    for a in args:
        if isinstance(a, cls):
            return a
    for v in kwargs.values():
        if isinstance(v, cls):
            return v
    return None

def is_channel_subscriber(func):
    from settings import logger
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            bot: Optional[Bot] = _find_in_args_kwargs(args, kwargs, Bot)

            # 1) Message | CallbackQuery | list[Message]
            msg: Optional[types.Message] = _find_in_args_kwargs(args, kwargs, types.Message)
            cb: Optional[types.CallbackQuery] = _find_in_args_kwargs(args, kwargs, types.CallbackQuery)

            messages_list: Optional[list[types.Message]] = None
            if msg is None and cb is None:
                for a in args:
                    if isinstance(a, list) and a and isinstance(a[0], types.Message):
                        messages_list = a
                        break
                if messages_list:
                    msg = messages_list[0]  # первый элемент альбома

            if bot is None or (msg is None and cb is None):
                # не нашли нужных объектов — не мешаем пайплайну
                return await func(*args, **kwargs)

            # 2) единоразовый показ на альбом
            media_group_id = None
            if messages_list:
                media_group_id = messages_list[0].media_group_id
            elif msg:
                media_group_id = msg.media_group_id

            if media_group_id:
                now = time.time()
                # очистка протухших записей
                for k, ts in list(_seen_media_groups.items()):
                    if now - ts > 60:
                        _seen_media_groups.pop(k, None)
                if media_group_id in _seen_media_groups:
                    # уже показывали для этого альбома — пропускаем
                    return
                _seen_media_groups[media_group_id] = now

            # 3) проверка подписки
            user_id = cb.from_user.id if cb else msg.from_user.id
            member = await bot.get_chat_member(sozdavai_channel_id, user_id)
            user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id)

            if member.status in {"member", "administrator", "creator"} or user_sub.type_subscription_id != 2:
                return await func(*args, **kwargs)

            # 4) нет подписки — показываем одно сообщение
            text = no_subscriber_message

            if cb:
                with contextlib.suppress(Exception):
                    await cb.answer()  # закрыть «крутилку»
                await cb.message.answer(
                    text, reply_markup=channel_sub_keyboard.as_markup(), parse_mode="HTML"
                )
            else:
                await msg.answer(
                    text, reply_markup=channel_sub_keyboard.as_markup(), parse_mode="HTML"
                )
            return

        except Exception:
            logger.log("ERROR_HANDLER", f"is_channel_subscriber\n\n{traceback.format_exc()}")
            return

    return wrapper