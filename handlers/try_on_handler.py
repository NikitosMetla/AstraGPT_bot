import io
import io
import traceback

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import any_state
from aiogram.types import Message, BufferedInputFile, CallbackQuery
from aiogram_media_group import media_group_handler

from data.keyboards import cancel_keyboard, choice_generation_mode_keyboard, subscriptions_keyboard, \
    more_generations_keyboard
from db.repository import users_repository, subscriptions_repository, type_subscriptions_repository, \
    generations_packets_repository
from settings import InputMessage, sub_text
from utils.is_subscriber import is_channel_subscriber, is_subscriber
from utils.new_fitroom_api import FitroomClient, CreditsFitroomAPIError

try_on_router = Router()


@try_on_router.message(F.text == "/try_on")
@try_on_router.message(F.text == "/tryon")
@is_channel_subscriber
@is_subscriber
async def profile_message(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
    type_sub = await type_subscriptions_repository.get_type_subscription_by_id(type_id=user_sub.type_subscription_id)
    delete_keyboard_message = await message.answer(text=f"""📸 Баланс Кредитов: {user_sub.photo_generations if type_sub.plan_name != "Ultima" else "∞"}

Загрузи своё фото для примерки!
     
✔️ Выбери снимок в хорошем качестве
✔️ В кадре должен быть один человек
✔️ Фигура должна быть хорошо видна

🔒 Твои фото не хранятся — обработка проходит мгновенно и безопасно!

Ниже ты можешь конкретизировать, какой тип одежды ты хочешь примерить. Если не указывать, автоматически включится режим - 🧥Полный образ (или платье)""")
    await delete_keyboard_message.edit_reply_markup(
        reply_markup=choice_generation_mode_keyboard(user_sub.photo_generations,
                                                     delete_keyboard_message_id=delete_keyboard_message.message_id).as_markup())
    await state.set_state(InputMessage.input_photo_people)


@try_on_router.callback_query(F.data.startswith("choice_generation_mode"), any_state)
@is_channel_subscriber
@is_subscriber
async def choice_generation_mode(call: CallbackQuery, state: FSMContext, bot: Bot):
    call_data = call.data.split("|")
    # state_data = await state.get_data()
    generations = int(call_data[2])
    mode_generation = call_data[1]
    delete_keyboard_message_id = int(call_data[3])
    now_state = await state.get_state()
    user_id = call.from_user.id
    if now_state is None:
        return
    if now_state == "InputMessage:input_photo_people":
        await state.update_data(mode_generation=mode_generation,
                                delete_keyboard_message_id=delete_keyboard_message_id)
        await call.message.delete_reply_markup()
        user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
        type_sub = await type_subscriptions_repository.get_type_subscription_by_id(
            type_id=user_sub.type_subscription_id)
        await call.message.edit_text(text=f"""📸 Баланс Кредитов: {generations if type_sub.plan_name != "Ultima" else "∞"}

Загрузи своё фото для примерки!

✔️ Выбери снимок в хорошем качестве
✔️ В кадре должен быть один человек
✔️ Фигура должна быть хорошо видна

🔒 Твои фото не хранятся — обработка проходит мгновенно и безопасно!

Ты выбрал режим - {'🧥Полный образ (или платье)' if mode_generation == 'full' else '👖Низ' if mode_generation == 'lower' else '👕Верх'}""",
                                     reply_markup=cancel_keyboard.as_markup())


@try_on_router.message(
    F.media_group_id,
    F.content_type == "photo",
    InputMessage.input_photo_clothes
)

@media_group_handler   # собираем в список
@is_channel_subscriber
async def handle_photo_album(messages: list[Message], state: FSMContext, bot: Bot):
    message = messages[0]
    await message.answer("Дорогой друг, нужно отправить <b>ТОЛЬКО ОДНУ</b> фотографию одежды, которую ты хочешь примерить!",
                         reply_markup=cancel_keyboard.as_markup())


@try_on_router.message(
    F.media_group_id,
    F.content_type == "photo",
    InputMessage.input_photo_people
)

@media_group_handler   # собираем в список
@is_channel_subscriber
async def handle_photo_album(messages: list[Message], state: FSMContext, bot: Bot):
    message = messages[0]
    await message.answer("Дорогой друг, нужно отправить <b>ТОЛЬКО ОДНУ</b> фотографию человека,"
                         " на которого ты хочешь примерить одежду!",
                         reply_markup=cancel_keyboard.as_markup())


@try_on_router.message(F.photo, InputMessage.input_photo_clothes)
@is_channel_subscriber
@is_subscriber
async def standard_message_photo_handler(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    state_data = await state.get_data()
    mode_generation = state_data.get("mode_generation")
    delete_message_id = state_data.get("delete_message_id")
    await bot.delete_message(message_id=delete_message_id,
                             chat_id=user_id)
    people_photo_id = state_data.get("people_photo_id")
    photo_bytes_io = io.BytesIO()
    people_photo_io = io.BytesIO()
    photo_id = message.photo[-1].file_id
    await users_repository.update_last_photo_id_by_user_id(photo_id=people_photo_id + ", " + photo_id, user_id=user_id)
    await bot.download(message.photo[-1], destination=photo_bytes_io)
    await bot.download(people_photo_id, destination=people_photo_io)
    people_photo_io.seek(0)
    photo_bytes_io.seek(0)
    model_bytes = people_photo_io.read()
    cloth_bytes = photo_bytes_io.read()

    await bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")
    client = FitroomClient()

    try:
        ai_photo = await client.try_on(
            validate=False,
            model_bytes=model_bytes,
            cloth_bytes=cloth_bytes,
            chat_id=user_id,
            send_bot=bot,
            cloth_type=mode_generation,  # или "lower", "full", "combo"
            timeout=150
        )
        user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
        await subscriptions_repository.update_generations(subscription_id=user_sub.id, new_generations=-1)
        photo_answer = await message.answer_photo(BufferedInputFile(file=ai_photo, filename="image.png"))
        await state.set_state(InputMessage.input_photo_people)
        generations = user_sub.photo_generations
        # await ai_requests_repository.add_request(user_id=user_id,
        #                                          people_photo=people_photo_id,
        #                                          clothes_photo=message.photo[-1].file_id,
        #                                          answer_photo=photo_answer.photo[-1].file_id)
        # print(generations)
        type_sub = await type_subscriptions_repository.get_type_subscription_by_id(type_id=user_sub.type_subscription_id)
        if type_sub.plan_name == "Smart" and user_sub.photo_generations - 1 <= 0:
            type_sub = await type_subscriptions_repository.get_type_subscription_by_id(
                type_id=user_sub.type_subscription_id
            ) if user_sub else None
            await state.clear()
            generations_packets = await generations_packets_repository.select_all_generations_packets()
            from settings import buy_generations_text
            sub_types = await type_subscriptions_repository.select_all_type_subscriptions()
            if type_sub and type_sub.plan_name == "Free":
                await bot.send_message(
                    chat_id=user_id,
                    text="🚨 Эта функция доступна только по подписке\n\n" + sub_text,
                    reply_markup=subscriptions_keyboard(sub_types).as_markup(),
                )

            await bot.send_message(
                chat_id=user_id,
                text=buy_generations_text,
                reply_markup=more_generations_keyboard(generations_packets).as_markup(),
            )
            return
        delete_keyboard_message = await message.answer(text=f"""📸 Баланс Кредитов: {generations - 1 if type_sub.plan_name != "Ultima" else "∞"}

Загрузи своё фото для примерки!

✔️ Выбери снимок в хорошем качестве
✔️ В кадре должен быть один человек
✔️ Фигура должна быть хорошо видна

🔒 Твои фото не хранятся — обработка проходит мгновенно и безопасно!

Ниже ты можешь конкретизировать, какой тип одежды ты хочешь примерить. Если не указывать, автоматически включится режим - 🧥Полный образ (или платье)""")
        await delete_keyboard_message.edit_reply_markup(
            reply_markup=choice_generation_mode_keyboard(generations=generations - 1,
                                                         delete_keyboard_message_id=delete_keyboard_message.message_id).as_markup())
    except CreditsFitroomAPIError:
        from settings import logger
        error_text = ("В связи с большим наплывом пользователей"
                     " наши сервера испытывают экстремальные нагрузки в примерке одежды."
                     " Скоро примерка станет снова доступна,"
                     " а пока можете воспользоваться другим функционалом."
                     " Я умею немало 🤗")
        # print(traceback.format_exc())
        logger.log("ERROR_HANDLER",
                   f"{user_id} | @{message.from_user.username} 🚫 Ошибка в обработке сообщения: {traceback.format_exc()}")
        await message.answer(text=error_text)
        await state.clear()
    except:
        from settings import logger
        # print(traceback.format_exc())
        logger.log("ERROR_HANDLER",
                   f"{user_id} | @{message.from_user.username} 🚫 Ошибка в обработке сообщения: {traceback.format_exc()}")
        await message.answer("🚫Дорогой друг, пожалуйста, убедись, что ты отправляешь фото человека и одежды и попробуй еще раз отправить оба фото заново")
        await state.clear()
    finally:
        await client.close()


@try_on_router.message(F.photo, InputMessage.input_photo_people)
async def standard_message_photo_handler(message: Message, bot: Bot, state: FSMContext):
    print(message.photo[-1].file_id)
    photo_id = message.photo[-1].file_id
    user_id = message.from_user.id
    state_data = await state.get_data()
    mode_generation = state_data.get("mode_generation")
    delete_keyboard_message_id = state_data.get("delete_keyboard_message_id")
    try:
        await bot.edit_message_reply_markup(message_id=delete_keyboard_message_id,
                                            chat_id=user_id)
    except:
        pass
    if mode_generation is None:
        mode_generation = 'full'
    user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
    if user_sub.photo_generations <= 0:
        type_sub = await type_subscriptions_repository.get_type_subscription_by_id(
            type_id=user_sub.type_subscription_id
        ) if user_sub else None
        await state.clear()
        generations_packets = await generations_packets_repository.select_all_generations_packets()
        from settings import buy_generations_text
        sub_types = await type_subscriptions_repository.select_all_type_subscriptions()
        if type_sub and type_sub.plan_name == "Free":

            await bot.send_message(
                chat_id=user_id,
                text="🚨 Эта функция доступна только по подписке\n\n" + sub_text,
                reply_markup=subscriptions_keyboard(sub_types).as_markup(),
            )

        await bot.send_message(
            chat_id=user_id,
            text=buy_generations_text,
            reply_markup=more_generations_keyboard(generations_packets).as_markup(),
        )
        return
    photo_id = message.photo[-1].file_id
    delete_message = await message.answer(
        "👗✨Отлично, теперь отправьте фото одежды, в которую вы хотите переодеть человека",
        reply_markup=cancel_keyboard.as_markup())
    await state.set_state(InputMessage.input_photo_clothes)
    await state.update_data(people_photo_id=photo_id, delete_message_id=delete_message.message_id,
                            mode_generation=mode_generation)