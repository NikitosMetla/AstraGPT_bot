import traceback
from functools import wraps

from aiogram.fsm.context import FSMContext

from aiogram import types, Bot

from data.keyboards import subscriptions_keyboard
from db.repository import admin_repository, subscriptions_repository, type_subscriptions_repository
from settings import sub_text


def is_subscriber(func):
    @wraps(func)
    async def wrapper(message: types.Message | types.CallbackQuery, state: FSMContext, bot: Bot, **kwargs):
        # print("========================= " + func.__name__ + " ============================")
        return await func(message, state, bot, **kwargs)
        # try:
        #     user_sub = await subscriptions_repository.get_active_subscription_by_user_id(message.from_user.id)
        #     type_sub = await type_subscriptions_repository.get_type_subscription_by_id(type_id=user_sub.type_subscription_id)
        #     print(type_sub.plan_name)
        #     print(user_sub)
        #     if user_sub and type_sub.plan_name != "Free":
        #         # print('Проверка на подписку пройдена')
        #         return await func(message, state, bot, **kwargs)
        #     elif type(message) == types.Message:
        #         # await message.delete()
        #         sub_types = await type_subscriptions_repository.select_all_type_subscriptions()
        #         await message.answer("🚨К сожалению, данная функция, которую ты"
        #                              " пытаешься использовать, доступна только по подписке\n\n" + sub_text,
        #                              reply_markup=subscriptions_keyboard(sub_types).as_markup())
        #     else:
        #         try:
        #             await message.message.delete()
        #         finally:
        #             sub_types = await type_subscriptions_repository.select_all_type_subscriptions()
        #             await message.message.answer("🚨К сожалению, данная функция, которую ты пытаешься"
        #                                          " использовать доступна только по подписке\n\n" + sub_text,
        #                                  reply_markup=subscriptions_keyboard(sub_types).as_markup())
        # except Exception:
        #     print(traceback.format_exc())
        # finally:
        #     # print("========================= " + func.__name__ + " ============================")

    return wrapper
