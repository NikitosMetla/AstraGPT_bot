# import datetime
# import io
# import io
# import traceback
#
# from aiogram import Router, F, Bot
# from aiogram.fsm.context import FSMContext
# from aiogram.fsm.state import any_state
# from aiogram.types import Message, BufferedInputFile, CallbackQuery
# from aiogram.utils.media_group import MediaGroupBuilder
#
# from data.keyboards import answer_user_keyboard, buy_sub_keyboard, buy_generations_keyboard, \
#     cancel_keyboard, confirm_cancel_sub_keyboard, choice_generation_mode_keyboard
# from db.repository import admin_repository, ai_requests_repository
# from db.repository import users_repository, subscriptions_repository
# from settings import InputMessage, standard_photo_id, give_individual_sub, logo_photo_id, examples_photo_ids
# from utils.new_fitroom_api import FitroomClient
#
# try_on_router = Router()
#
#
# @try_on_router.message(F.text == "/try_on")
# async def profile_message(message: Message, state: FSMContext):
#     user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=message.from_user.id)
#     user_id = message.from_user.id
#     if user_sub is None:
#         await message.answer("""🔓 Откройте весь потенциал нашего бота — оформите подписку прямо здесь.
#
# <b>Доступные тарифы:</b>
# • <b>Стандарт</b>  — 990 ₽/мес: 70 генераций
# • <b>Премиум</b> — 1290 ₽/мес: 100 генераций
#
# 👉 Политика персональных данных: https://disk.yandex.ru/i/npUQ8IiY1YoUZQ
# politics
# 👉 Публичная оферта: https://disk.yandex.ru/i/hZ4fSqrOABSchQ
#
# 📅 Подписка активируется мгновенно и продлевается автоматически каждый месяц. Отменить в любой момент можно в настройках.
#
# 😊 Выберите подходящий тариф и нажмите «Оплатить» — мы уже готовы помочь!""",
#                              reply_markup=buy_sub_keyboard(False).as_markup(),
#                              disable_web_page_preview=True)
#         await give_individual_sub(message, user_id, 10800)
#         return
#     generations = user_sub.monthly_quota + user_sub.carried_over - user_sub.used_count
#     delete_keyboard_message = await message.answer_photo(caption=f"""📸 Баланс Кредитов: {generations}
#
# Загрузи своё фото для примерки!
#
# ✔️ Выбери снимок в хорошем качестве
# ✔️ В кадре должен быть один человек
# ✔️ Фигура должна быть хорошо видна
#
# 🔒 Твои фото не хранятся — обработка проходит мгновенно и безопасно!
#
# Ниже ты можешь конкретизировать, какой тип одежды ты хочешь примерить. Если не указывать, автоматически включится режим - 🧥Полный образ(или платье)""",
#                            photo=standard_photo_id)
#     await delete_keyboard_message.edit_reply_markup(
#         reply_markup=choice_generation_mode_keyboard(generations=generations,
#                                                      delete_keyboard_message_id=delete_keyboard_message.message_id).as_markup())
#     await state.set_state(InputMessage.input_photo_people)
#
#
# @try_on_router.callback_query(F.data.startswith("choice_generation_mode"), any_state)
# async def choice_generation_mode(call: CallbackQuery, state: FSMContext):
#     call_data = call.data.split("|")
#     # state_data = await state.get_data()
#     generations = int(call_data[2])
#     mode_generation = call_data[1]
#     delete_keyboard_message_id = int(call_data[3])
#     now_state = await state.get_state()
#     if now_state is None:
#         return
#     if now_state == "InputMessage:input_photo_people":
#         await state.update_data(mode_generation=mode_generation,
#                                 delete_keyboard_message_id=delete_keyboard_message_id)
#         await call.message.delete_reply_markup()
#         await call.message.edit_caption(caption=f"""📸 Баланс Кредитов: {generations}
#
# Загрузи своё фото для примерки!
#
# ✔️ Выбери снимок в хорошем качестве
# ✔️ В кадре должен быть один человек
# ✔️ Фигура должна быть хорошо видна
#
# 🔒 Твои фото не хранятся — обработка проходит мгновенно и безопасно!
#
# Ты выбрал режим - {'🧥Полный образ(или платье)' if mode_generation == 'full' else '👖Низ' if mode_generation == 'lower' else '👕Верх'}""",
#                                      reply_markup=cancel_keyboard.as_markup())
#
#
# @try_on_router.message(F.text == "/profile")
# async def profile_message(message: Message):
#     user_id = message.from_user.id
#     user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
#     generations = 0
#     if user_sub is not None:
#         generations = user_sub.monthly_quota + user_sub.carried_over - user_sub.used_count
#     media_group = MediaGroupBuilder(caption=f"🔢 У тебя осталось {generations} генераций в этом месяце. 🎁")
#     for photo_id in examples_photo_ids:
#         media_group.add_photo(media=photo_id)
#     await message.answer_media_group(media=media_group.build())
#
# @try_on_router.message(F.text == "/support")
# async def profile_message(message: Message, state: FSMContext):
#     await message.answer("✍️ Опишите вашу проблему, идею или пожелание, и наш менеджер скоро свяжется с вами. 📞")
#     await state.set_state(InputMessage.enter_support)
#
#
# @try_on_router.message(F.text, InputMessage.enter_support)
# async def send_text_message(message: Message, bot: Bot, state: FSMContext):
#     admins = await admin_repository.select_all_admins()
#     from bot_admin import admin_bot
#     for admin in admins:
#         try:
#             await admin_bot.send_message(chat_id=admin.admin_id,
#                                    text=f"Вопрос от пользователя {message.from_user.username} c"
#                                         f" id {message.from_user.id}:\n\n{message.text}",
#                                    reply_markup=answer_user_keyboard(message.from_user.id,
#                                                                      user_name=message.from_user.username).as_markup())
#         except:
#             continue
#     await message.answer("🙏 Спасибо за обращение! Наш менеджер свяжется с вами в ближайшее время. 📞")
#     await state.clear()
#
#
#
# @try_on_router.message(F.text)
# async def send_text_message(message: Message):
#     await message.answer("К сожалению, мы пока не работаем с текстовыми запросами. Вы можете прислать фотографии для примерки по-отдельности👗✨")
#
#
# @try_on_router.message(F.photo, InputMessage.input_photo_clothes)
# async def standard_message_photo_handler(message: Message, bot: Bot, state: FSMContext):
#     # from bot import fitroom_client
#     user_id = message.from_user.id
#     user = await users_repository.get_user_by_user_id(user_id=user_id)
#     state_data = await state.get_data()
#     mode_generation = state_data.get("mode_generation")
#     delete_message_id = state_data.get("delete_message_id")
#     await bot.delete_message(message_id=delete_message_id,
#                              chat_id=user_id)
#     people_photo_id = state_data.get("people_photo_id")
#     await bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")
#     # delete_message = await bot.send_message(chat_id=user.user_id,
#     #                                              text="🎨Начал работу над изображением, немного магии…")
#     photo_bytes_io = io.BytesIO()
#     people_photo_io = io.BytesIO()
#     photo_id = message.photo[-1].file_id
#     await users_repository.update_last_photo_id_by_user_id(photo_id=people_photo_id + ", " + photo_id, user_id=user_id)
#     await bot.download(message.photo[-1], destination=photo_bytes_io)
#     await bot.download(people_photo_id, destination=people_photo_io)
#     people_photo_io.seek(0)
#     photo_bytes_io.seek(0)
#     model_bytes = people_photo_io.read()
#     cloth_bytes = photo_bytes_io.read()
#
#     await bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")
#     client = FitroomClient()
#
#     try:
#         ai_photo = await client.try_on(
#             validate=False,
#             model_bytes=model_bytes,
#             cloth_bytes=cloth_bytes,
#             chat_id=user_id,
#             send_bot=bot,
#             cloth_type=mode_generation,  # или "lower", "full", "combo"
#             timeout=150
#         )
#         user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
#         await subscriptions_repository.update_used_count(subscription_id=user_sub.id,
#                                                          used=1)
#         photo_answer = await message.answer_photo(BufferedInputFile(file=ai_photo, filename="image.png"))
#         await state.set_state(InputMessage.input_photo_people)
#         generations = user_sub.monthly_quota + user_sub.carried_over - user_sub.used_count
#         await ai_requests_repository.add_request(user_id=user_id,
#                                                  people_photo=people_photo_id,
#                                                  clothes_photo=message.photo[-1].file_id,
#                                                  answer_photo=photo_answer.photo[-1].file_id)
#         # print(generations)
#         if generations - 1 <= 0:
#             if user_sub is None:
#                 await users_repository.update_last_photo_id_by_user_id(photo_id=photo_id,
#                                                                        user_id=user_id)
#                 await message.answer("""📸 Уважаемый пользователь, у вас пока нет активной подписки.
#
# <b>Доступные тарифы:</b>
# • <b>Стандарт</b>  — 990 ₽/мес: 70 генераций
# • <b>Премиум</b> — 1290 ₽/мес: 100 генераций
#
# 👉 Политика персональных данных: https://disk.yandex.ru/i/npUQ8IiY1YoUZQ
# politics
# 👉 Публичная оферта: https://disk.yandex.ru/i/hZ4fSqrOABSchQ
#
# 📅 Подписка активируется мгновенно и продлевается автоматически каждый месяц. Отменить в любой момент можно в настройках.
#
# 😊 Выберите подходящий тариф и нажмите «Оплатить» — мы уже готовы помочь!
#             """,
#                                      reply_markup=buy_sub_keyboard().as_markup(),
#                                      disable_web_page_preview=True)
#                 await state.clear()
#                 await give_individual_sub(message, user_id, 10800)
#                 return
#             if generations - 1 <= 0 and user_sub.plan_name != "Free":
#                 await state.clear()
#                 await users_repository.update_last_photo_id_by_user_id(photo_id=photo_id,
#                                                                        user_id=user_id)
#                 await message.answer("""📸 У вас закончились доступные генерации.
#
# <b>Доступные пакеты докупа:</b>
# • <b>Докуп 1</b> — 249 ₽: 10 генераций
# • <b>Докуп 2</b> — 449 ₽: 20 генераций
# • <b>Докуп 3</b> — 849 ₽: 40 генераций
#
# 👉 Политика персональных данных: https://disk.yandex.ru/i/npUQ8IiY1YoUZQ
# politics
# 👉 Публичная оферта: https://disk.yandex.ru/i/hZ4fSqrOABSchQ
#
# 📅 Пакет активируется мгновенно и не продлевается автоматически. Отменять ничего не нужно — после расхода вы снова увидите предложение докупить.
#
# 😊 Выберите подходящий пакет и нажмите «Оплатить», чтобы продолжить генерировать контент!
#             """,
#                                      reply_markup=buy_generations_keyboard.as_markup(),
#                                      disable_web_page_preview=True)
#                 return
#             elif generations - 1 <= 0 and user_sub.plan_name == "Free":
#                 await users_repository.update_last_photo_id_by_user_id(photo_id=photo_id,
#                                                                        user_id=user_id)
#                 await message.answer("""📸 Уважаемый пользователь, у вас пока нет активной подписки.
#
# <b>Доступные тарифы:</b>
# • <b>Стандарт</b>  — 990 ₽/мес: 70 генераций
# • <b>Премиум</b> — 1290 ₽/мес: 100 генераций
#
# 👉 Политика персональных данных: https://disk.yandex.ru/i/npUQ8IiY1YoUZQ
# politics
# 👉 Публичная оферта: https://disk.yandex.ru/i/hZ4fSqrOABSchQ
#
# 📅 Подписка активируется мгновенно и продлевается автоматически каждый месяц. Отменить в любой момент можно в настройках.
#
# 😊 Выберите подходящий тариф и нажмите «Оплатить» — мы уже готовы помочь!
#                     """,
#                                      reply_markup=buy_sub_keyboard().as_markup(),
#                                      disable_web_page_preview=True)
#                 await state.clear()
#                 await give_individual_sub(message, user_id, 10800)
#                 return
#         delete_keyboard_message = await message.answer_photo(caption=f"""📸 Баланс Кредитов: {generations - 1}
#
# Загрузи своё фото для примерки!
#
# ✔️ Выбери снимок в хорошем качестве
# ✔️ В кадре должен быть один человек
# ✔️ Фигура должна быть хорошо видна
#
# 🔒 Твои фото не хранятся — обработка проходит мгновенно и безопасно!
#
# Ниже ты можешь конкретизировать, какой тип одежды ты хочешь примерить. Если не указывать, автоматически включится режим - 🧥Полный образ(или платье)""",
#                                                              photo=standard_photo_id)
#         await delete_keyboard_message.edit_reply_markup(
#             reply_markup=choice_generation_mode_keyboard(generations=generations - 1,
#                                                          delete_keyboard_message_id=delete_keyboard_message.message_id).as_markup())
#     except:
#         from bot import logger
#         # print(traceback.format_exc())
#         logger.log("ERROR_HANDLER",
#                    f"{user_id} | @{message.from_user.username} 🚫 Ошибка в обработке сообщения: {traceback.format_exc()}")
#         await message.answer("🚫Дорогой друг, пожалуйста, убедись, что ты отправляешь фото человека и одежды и попробуй еще раз отправить оба фото заново")
#         await state.clear()
#     finally:
#         await client.close()
#
#
# @try_on_router.message(F.photo)
# @try_on_router.message(F.photo, InputMessage.input_photo_people)
# async def standard_message_photo_handler(message: Message, bot: Bot, state: FSMContext):
#     print(message.photo[-1].file_id)
#     photo_id = message.photo[-1].file_id
#     user_id = message.from_user.id
#     state_data = await state.get_data()
#     mode_generation = state_data.get("mode_generation")
#     delete_keyboard_message_id = state_data.get("delete_keyboard_message_id")
#     try:
#         await bot.edit_message_reply_markup(message_id=delete_keyboard_message_id,
#                                             chat_id=user_id)
#     except:
#         pass
#     if mode_generation is None:
#         mode_generation = 'full'
#     user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
#     print(user_sub)
#     if user_sub is None:
#         await users_repository.update_last_photo_id_by_user_id(photo_id=photo_id,
#                                                                user_id=user_id)
#         await message.answer("""📸 Уважаемый пользователь, у вас пока нет активной подписки.
#
# <b>Доступные тарифы:</b>
# • <b>Стандарт</b>  — 990 ₽/мес: 70 генераций
# • <b>Премиум</b> — 1290 ₽/мес: 100 генераций
#
# 👉 Политика персональных данных: https://disk.yandex.ru/i/npUQ8IiY1YoUZQ
# politics
# 👉 Публичная оферта: https://disk.yandex.ru/i/hZ4fSqrOABSchQ
#
# 📅 Подписка активируется мгновенно и продлевается автоматически каждый месяц. Отменить в любой момент можно в настройках.
#
# 😊 Выберите подходящий тариф и нажмите «Оплатить» — мы уже готовы помочь!
# """,
#                              reply_markup=buy_sub_keyboard().as_markup(),
#                              disable_web_page_preview=True)
#         await state.clear()
#         await give_individual_sub(message, user_id, 10800)
#         return
#     if user_sub.monthly_quota + user_sub.carried_over - user_sub.used_count <= 0 and user_sub.plan_name != "Free":
#         await state.clear()
#         await users_repository.update_last_photo_id_by_user_id(photo_id=photo_id,
#                                                                user_id=user_id)
#         await message.answer("""📸 У вас закончились доступные генерации.
#
# <b>Доступные пакеты докупа:</b>
# • <b>Докуп 1</b> — 249 ₽: 10 генераций
# • <b>Докуп 2</b> — 449 ₽: 20 генераций
# • <b>Докуп 3</b> — 849 ₽: 40 генераций
#
# 👉 Политика персональных данных: https://disk.yandex.ru/i/npUQ8IiY1YoUZQ
# politics
# 👉 Публичная оферта: https://disk.yandex.ru/i/hZ4fSqrOABSchQ
#
# 📅 Пакет активируется мгновенно и не продлевается автоматически. Отменять ничего не нужно — после расхода вы снова увидите предложение докупить.
#
# 😊 Выберите подходящий пакет и нажмите «Оплатить», чтобы продолжить генерировать контент!
# """,
#                              reply_markup=buy_generations_keyboard.as_markup(),
#                              disable_web_page_preview=True)
#         return
#     elif user_sub.monthly_quota + user_sub.carried_over - user_sub.used_count <= 0 and user_sub.plan_name == "Free":
#         await users_repository.update_last_photo_id_by_user_id(photo_id=photo_id,
#                                                                user_id=user_id)
#         await message.answer("""📸 Уважаемый пользователь, у вас пока нет активной подписки.
#
# <b>Доступные тарифы:</b>
# • <b>Стандарт</b>  — 990 ₽/мес: 70 генераций
# • <b>Премиум</b> — 1290 ₽/мес: 100 генераций
#
# 👉 Политика персональных данных: https://disk.yandex.ru/i/npUQ8IiY1YoUZQ
# politics
# 👉 Публичная оферта: https://disk.yandex.ru/i/hZ4fSqrOABSchQ
#
# 📅 Подписка активируется мгновенно и продлевается автоматически каждый месяц. Отменить в любой момент можно в настройках.
#
# 😊 Выберите подходящий тариф и нажмите «Оплатить» — мы уже готовы помочь!
#         """,
#                              reply_markup=buy_sub_keyboard().as_markup(),
#                              disable_web_page_preview=True)
#         await state.clear()
#         await give_individual_sub(message, user_id, 10800)
#         return
#     photo_id = message.photo[-1].file_id
#     delete_message = await message.answer(
#         "👗✨Отлично, теперь отправьте фото одежды, в которую вы хотите переодеть человека",
#         reply_markup=cancel_keyboard.as_markup())
#     await state.set_state(InputMessage.input_photo_clothes)
#     await state.update_data(people_photo_id=photo_id, delete_message_id=delete_message.message_id,
#                             mode_generation=mode_generation)
#
#
#
#
#
