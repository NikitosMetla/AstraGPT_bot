import io
import pprint
import traceback
from datetime import datetime, timedelta

from aiogram import Router, F, Bot, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import any_state
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InputMediaPhoto
from aiogram.utils.chat_action import ChatActionSender
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram_media_group import media_group_handler

from data.keyboards import profiles_keyboard, cancel_keyboard, settings_keyboard, \
    confirm_clear_context, buy_sub_keyboard, subscriptions_keyboard, delete_payment_keyboard, unlink_card_keyboard, \
    confirm_delete_notification_keyboard, delete_notification_keyboard
from db.repository import users_repository, ai_requests_repository, subscriptions_repository, \
    type_subscriptions_repository, notifications_repository, referral_system_repository, promo_activations_repository, \
    dialogs_messages_repository
from settings import InputMessage, photos_pages, OPENAI_ALLOWED_DOC_EXTS, get_current_assistant, sub_text, \
    gemini_images_client, SUPPORTED_TEXT_FILE_TYPES
from utils.completions_gpt_tools import NoSubscription, NoGenerations
from utils.is_subscriber import is_subscriber, is_channel_subscriber
from utils.paginator import MechanicsPaginator
from utils.parse_gpt_text import split_telegram_html, sanitize_with_links

standard_router = Router()



async def process_ai_response(ai_response, message: Message, user_id: int, bot: Bot, request_text: str = None, photo_id: str = None, has_photo: bool = False, has_audio: bool = False, has_files: bool = False, file_id: str = None):
    """
    Обрабатывает ответ от GPT в формате final_content и отправляет пользователю
    """
    from aiogram.enums import ParseMode
    
    # Если ответ не является словарем (обратная совместимость), преобразуем
    if not isinstance(ai_response, dict):
        ai_response = {"text": str(ai_response), "image_files": [], "files": [], "audio_file": None, "reply_markup": None}
    
    # Извлекаем данные из final_content
    text = ai_response.get("text", "")
    image_files = ai_response.get("image_files", [])
    files = ai_response.get("files", [])
    audio_file = ai_response.get("audio_file")
    reply_markup: InlineKeyboardBuilder | None = ai_response.get("reply_markup", None)
    
    # Обработка файлов (документы, изображения от ассистента)
    if files:
        for file_data in files:
            try:
                await message.reply_document(
                    document=BufferedInputFile(
                        file=file_data.get("bytes"),
                        filename=file_data.get("filename")
                    ),
                    reply_markup=reply_markup.as_markup() if reply_markup else None,
                )
                text = text or "🤖Сгенерированный файл"
            except Exception:
                print(traceback.format_exc())
                await message.answer("Возникла ошибка при отправке файла, попробуй еще раз",
                                     reply_markup=reply_markup.as_markup() if reply_markup else None,)
                return
    
    # Обработка изображений
    if image_files:
        photos_ids = []
        for raw in image_files:
            buffer = io.BytesIO(raw)
            buffer.seek(0)

            photo = BufferedInputFile(file=buffer.getvalue(), filename="image.png")
            reply_message = await message.reply_photo(
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                photo=photo,
                reply_markup=reply_markup.as_markup() if reply_markup else None,
            )
            photos_ids.append(reply_message.photo[-1].file_id)
        await users_repository.update_last_photo_id_by_user_id(
            photo_id=", ".join(photos_ids),
            user_id=user_id
        )
    else:
        # Обработка текстового ответа
        if text:
            text = sanitize_with_links(text)
            split_messages = split_telegram_html(text)
            for chunk in split_messages:
                await message.reply(
                    chunk,
                    disable_web_page_preview=True,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup.as_markup() if reply_markup else None,
                )

    # Сохранение запроса в БД
    await ai_requests_repository.add_request(
        user_id=user_id,
        answer_ai=text if text and text != "" else "Выдал файл или фото",
        user_question=request_text,
        generate_images=bool(image_files),
        has_photo=has_photo,
        photo_id=photo_id,
        has_audio=has_audio,
        has_files=has_files,
        file_id=file_id
    )


@standard_router.message(F.text == "/enter_promocode", any_state)
@is_channel_subscriber
async def command_enter_promocode(message: Message | CallbackQuery, state: FSMContext, bot: Bot):
    await state.set_state(InputMessage.enter_promocode)
    delete_message = await message.answer("Дорогой друг, введи промокод, который ты хочешь активировать",
                         reply_markup=cancel_keyboard.as_markup())
    await state.update_data(delete_message_id=delete_message.message_id)


@standard_router.message(F.text, InputMessage.enter_promocode)
@is_channel_subscriber
async def route_enter_promocode(message: Message, state: FSMContext, bot: Bot):
    promo_code = message.text
    user_id = message.from_user.id
    state_data = await state.get_data()
    delete_message_id = state_data.get("delete_message_id")
    if delete_message_id is not None:
        try:
            await bot.delete_message(chat_id=user_id, message_id=delete_message_id)
        except:
            pass
    promo = await referral_system_repository.get_promo_by_promo_code(promo_code=promo_code)
    if promo is None:
        await message.answer("Такого промокода не существует",
                             reply_markup=cancel_keyboard.as_markup())
        return
    await state.clear()
    # delete_message = await message.answer("Секундочку, загружаем информацию о промокоде)")
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    promo_activations = await promo_activations_repository.get_user_ids_activations_by_promo_id(promo_id=promo.id)
    if user_id in promo_activations:
        await message.answer("К сожалению, мы вынуждены отказать. Ты уже активировал данные бонусы ранее")
        return
    await referral_system_repository.update_activations_by_promo_id(promo_id=promo.id)
    await promo_activations_repository.add_activation(promo_id=promo.id, activate_user_id=user_id)
    activate_user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
    user_sub_type = await type_subscriptions_repository.get_type_subscription_by_id(type_id=activate_user_sub.type_subscription_id)
    if activate_user_sub is None or (user_sub_type and user_sub_type.plan_name == "Free"):
        promo_sub_type = await type_subscriptions_repository.get_type_subscription_by_plan_name(plan_name=f"promo_{promo_code}")
        await subscriptions_repository.add_subscription(user_id=user_id,
                                                        time_limit_subscription=promo.days_sub,
                                                        photo_generations=promo.max_generations,
                                                        type_sub_id=promo_sub_type.id,
                                                        is_paid_sub=False
                                                        )
        end_date = datetime.now() + timedelta(days=promo.days_sub)
        text = f"✅ Теперь у тебя есть <b>подписка</b>! Подписка действует до {end_date.strftime('%d.%m.%y, %H:%M')} (GMT+3)"
    else:
        await subscriptions_repository.update_time_limit_subscription(subscription_id=activate_user_sub.id,
                                                                      new_time_limit=promo.days_sub)
        await subscriptions_repository.update_generations(subscription_id=activate_user_sub.id,
                                                          new_generations=promo.max_generations)
        end_date = activate_user_sub.last_billing_date + timedelta(days=activate_user_sub.time_limit_subscription + promo.days_sub)
        text = f"✅ К текущему плану тебе добавили <b>{timedelta(days=promo.days_sub).days} дней</b>! Подписка действует до {end_date.strftime('%d.%m.%y, %H:%M')} (GMT+3)"
    await message.answer(text=text)
    from settings import logger
    logger.log("PROMO_ACTIVATED", f"✅ USER {user_id} | {user.username} ACTIVATE PROMO: {promo.id} | {promo.promo_code}")



@standard_router.callback_query(F.data.startswith("delete_notification"))
@is_channel_subscriber
async def delete_notification_handler(call: CallbackQuery, state: FSMContext, bot: Bot):
    call_data = call.data.split("|")
    notif_id = int(call_data[1])
    notif = await notifications_repository.get_notification_info_by_id(id=notif_id)
    await call.message.edit_text(text=f'Ты уверен, что готов удалить уведомление об:'
                                      f' "{notif.text_notification}", которое должно'
                                      f' прийти {notif.when_send.strftime("%d-%m-%Y %H:%M")}?',
                                 reply_markup=confirm_delete_notification_keyboard(notif_id).as_markup())

@standard_router.callback_query(F.data.startswith("confirm_delete_notification|"))
@is_channel_subscriber
async def confirm_delete_notification_handler(call: CallbackQuery, state: FSMContext, bot: Bot):
    call_data = call.data.split("|")
    answer = call_data[1]
    notif_id = int(call_data[2])
    notif = await notifications_repository.get_notification_info_by_id(id=notif_id)
    if answer == "yes":
        await notifications_repository.delete_active_by_notification_id(notification_id=notif_id)
        await call.message.answer(f'✅Отлично, отменили твое напоминание об - "{notif.text_notification}"'
                                  f' на {notif.when_send.strftime("%d-%m-%Y %H:%M")}')
        await call.message.delete()
        return
    text = (f"✅ Отлично! Уведомление установлено на {notif.when_send.strftime('%d-%m-%Y %H:%M')}"
            f" по московскому времени\n\n📝 Текст напоминания: {notif.text_notification}")
    await call.message.edit_text(text=text, reply_markup=delete_notification_keyboard(notif_id).as_markup())


@standard_router.callback_query(F.data == "delete_payment", any_state)
@standard_router.message(F.text == "/unlink_card", any_state)
@is_channel_subscriber
async def sub_message(message: Message | CallbackQuery, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
    if user_sub:
        type_sub = await type_subscriptions_repository.get_type_subscription_by_id(type_id=user_sub.type_subscription_id)
    else:
        type_sub = None
    if type(message) == Message:
        if user_sub is None or (type_sub and type_sub.plan_name == "Free"):
            await message.answer("✨Дорогой друг, на данный момент у тебя нет активной подписки и привязанной карты в частности")
            return
        await message.answer("Ты уверен, что хочешь отвязать карту для оплаты подписки? После этого"
                             " твоя подписка не сможет автоматически продлеваться",
                             reply_markup=unlink_card_keyboard.as_markup())
    else:
        if user_sub is None or (type_sub and type_sub.plan_name == "Free"):
            await message.message.answer("✨Дорогой друг, на данный момент у тебя нет активной подписки и привязанной карты в частности")
            return
        await message.message.delete()
        if user_sub.method_id:
            await message.message.answer("Ты уверен, что хочешь отвязать карту для оплаты подписки? После этого"
                                 " твоя подписка не сможет автоматически продлеваться",
                                 reply_markup=unlink_card_keyboard.as_markup())
        else:
            await message.message.answer("Дорогой друг, у тебя есть активная подписка, но не видим у тебя привязанной"
                                         " карты. При истечении активной подписки будет необходимо произвести оплату заново")


@standard_router.callback_query(F.data == "unlink_card", any_state)
@is_channel_subscriber
async def sub_message(call: CallbackQuery, state: FSMContext, bot: Bot):
    user_id = call.from_user.id
    user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
    if user_sub:
        type_sub = await type_subscriptions_repository.get_type_subscription_by_id(
            type_id=user_sub.type_subscription_id)
    else:
        type_sub = None
    if user_sub is None or (type_sub and type_sub.plan_name == "Free"):
        await call.message.answer(
            "✨Дорогой друг, на данный момент у тебя нет активной подписки и привязанной карты в частности")
        return
    if user_sub.method_id is None:
        await call.message.answer(
            "✨Дорогой друг, на данный момент у тебя уже не привязана никакая карта")
        return
    await subscriptions_repository.delete_payment_method(sub_id=user_sub.id)
    await call.message.delete()
    await call.message.answer("Отлично, отвязали твой метод оплаты. Теперь твоя подписка не сможет продлеваться автоматически")


@standard_router.message(F.text == "/subscribe", any_state)
@is_channel_subscriber
async def sub_message(message: Message, state: FSMContext, bot: Bot):
    # await message.answer("✨Дорогой друг, на данный момент бот находится в бета-тесте и у тебя"
    #                      " имеется неограниченный доступ ко всему функционалу")
    user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=message.from_user.id)
    type_sub = await type_subscriptions_repository.get_type_subscription_by_id(type_id=user_sub.type_subscription_id)
    if user_sub is None or type_sub.plan_name == "Free":
        sub_types = await type_subscriptions_repository.select_all_type_subscriptions()
        await message.answer(sub_text,
                                  reply_markup=subscriptions_keyboard(sub_types).as_markup())
    else:
        await message.answer(f"Дорогой друг, на данный момент у тебя подключена подписка"
                             f" - {type_sub.plan_name} за {type_sub.price} рублей в месяц."
                             " Если ты хочешь отвязать карту, то нажми на кнопку ниже",
                             reply_markup=delete_payment_keyboard.as_markup())


@standard_router.callback_query(F.data.startswith("mechanics_paginator"))
@is_channel_subscriber
async def get_page_paginator(call: CallbackQuery, state: FSMContext):
    call_data = call.data.split(":")
    page_now = int(call_data[2])
    paginator = MechanicsPaginator(page_now)
    if call_data[1] == "page_prev_keys":
        keyboard = paginator.generate_prev_page()
        await call.message.edit_media(media=InputMediaPhoto(media=photos_pages.get(paginator.page_now)),
                                      reply_markup=keyboard)

    elif call_data[1] == "page_next_keys":
        keyboard = paginator.generate_next_page()
        await call.message.edit_media(media=InputMediaPhoto(media=photos_pages.get(paginator.page_now)),
                                      reply_markup=keyboard)


@standard_router.message(F.text == "/instructions", any_state)
@standard_router.message(F.text == "/start", any_state)
@is_channel_subscriber
async def send_user_message(message: Message, state: FSMContext, bot: Bot, user_data):
    paginator = MechanicsPaginator(page_now=1)
    keyboard = paginator.generate_now_page()
    try:
        await message.answer_photo(photo=photos_pages.get(paginator.page_now),
                                   reply_markup=keyboard)
    except:
        await message.answer("Привет! Ты можешь задавать мне разные вопросы и я могу помогать тебе решать разные задачи!")


@standard_router.message(F.text == "/profile", any_state)
@is_channel_subscriber
async def send_user_message(message: Message, state: FSMContext, bot: Bot):
    user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=message.from_user.id)
    type_sub = await type_subscriptions_repository.get_type_subscription_by_id(type_id=user_sub.type_subscription_id)
    date_now = datetime.now().date()
    days_left = user_sub.last_billing_date.date() + timedelta(days=user_sub.time_limit_subscription) - date_now
    await message.answer(f'👤 Твой профиль\n\n✓ Подписка: {type_sub.plan_name}\nДней до окончания:'
                         f' {days_left.days if type_sub.plan_name != "Free" else "Без ограничений"}\n'
                         f'✓ Доступ: {"Полный ко всем функциям" if type_sub.plan_name != "Free" else "Базовое общение с агентом"}'
                         f'\n\n✨ Персонализация\nХочешь идеальные ответы? Расскажи о себе в '
                         '"Настройке контекста"! Бот учтёт это, например, при:\n- Составлении резюме\n- '
                         'Написании персональных текстов\n- Составлении индивидуальных рекомендаций\n\nЧем больше знает бот — тем точнее помогает!',
                         reply_markup=profiles_keyboard.as_markup())
    # await message.answer(f'👤 Твой профиль\n\n✓ Доступ: Полный ко всем функциям'
    #                      f'\n\n✨ Персонализация\nХочешь идеальные ответы? Расскажи о себе в '
    #                      '"Настройке контекста"! Бот учтёт это, например, при:\n- Составлении резюме\n- '
    #                      'Написании персональных текстов\n- Составлении индивидуальных рекомендаций\n\nЧем больше знает бот — тем точнее помогает!',
    #                      reply_markup=profiles_keyboard.as_markup())


@standard_router.message(F.text == "/clear_context", any_state)
@is_channel_subscriber
async def send_user_message(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await message.answer('Ты уверен, что хочешь очистить контекст данного диалога?',
                         reply_markup=confirm_clear_context.as_markup())

@standard_router.callback_query(F.data == "clear_context", any_state)
@is_channel_subscriber
async def send_user_message(call: CallbackQuery, state: FSMContext, bot: Bot):
    user_id = call.from_user.id
    await dialogs_messages_repository.delete_messages_by_user_id(user_id=user_id)
    # await users_repository.update_thread_id_by_user_id(user_id=user_id, thread_id=None)
    await call.message.delete()
    await call.message.answer("Контекст твоего диалога очищен✨")

@standard_router.callback_query(F.data == "not_clear_context", any_state)
@is_channel_subscriber
async def send_user_message(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.message.delete()


@standard_router.message(F.text == "/settings", any_state)
@is_channel_subscriber
async def send_user_message(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await message.answer('👤 🤖 Выбери режим работы\n\n• Универсальный — быстрые ответы на повседневные'
                         ' вопросы 😎\n• Специализированный — анализ данных, код и сложные запросы 🧠\n\nПросто'
                         ' нажми на нужный вариант — и мы сразу поможем!',
                         reply_markup=settings_keyboard.as_markup())


@standard_router.message(F.text == "/support", any_state)
async def send_user_message(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await message.answer('☎️ Дорогой друг, чтобы связаться с нами - напиши в наш чат поддержки @sozdav_ai')


@standard_router.callback_query(F.data == "edit_user_context", any_state)
@is_channel_subscriber
async def send_user_message(call: CallbackQuery, state: FSMContext, bot: Bot):
    user = await users_repository.get_user_by_user_id(user_id=call.from_user.id)
    delete_message = await call.message.answer(f"AstraGPT запомнит всю информацию, которую вы сейчас"
                              f" введете и будет учитывать ее при составлении ответов для вас!\n\nВаш нынешний контекст:\n{user.context}",
                              reply_markup=cancel_keyboard.as_markup())
    await state.set_state(InputMessage.enter_user_context_state)
    await call.message.delete()
    await state.update_data(delete_message_id=delete_message.message_id)


@standard_router.callback_query(F.data.startswith("mode|"), any_state)
@is_channel_subscriber
@is_subscriber
async def send_user_message(call: CallbackQuery, state: FSMContext, bot: Bot):
    mode = call.data.split("|")[1]
    chat = await bot.get_chat(call.from_user.id)
    pinned = chat.pinned_message
    if pinned is not None:
        result= await bot.unpin_chat_message(
            chat_id=call.from_user.id,
            message_id=pinned.message_id  # ID открепляемого сообщения
        )
    if mode == "universal":
        await users_repository.update_model_type_by_user_id(model_type="gpt-4.1-mini", user_id=call.from_user.id)
        pin_message = await call.message.answer("Активная модель - 🤖Универсальная")
    else:
        await users_repository.update_model_type_by_user_id(model_type="gpt-4.1", user_id=call.from_user.id)
        pin_message = await call.message.answer("Активная модель - 🧠Специализированная")
    await pin_message.pin()
    await call.message.delete()


@standard_router.callback_query(F.data == "cancel", any_state)
@is_channel_subscriber
async def send_user_message(call: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    await call.message.delete()


@standard_router.message(F.text, InputMessage.enter_user_context_state)
@is_channel_subscriber
async def standard_message_handler(message: Message, state: FSMContext, bot: Bot):
    state_data = await state.get_data()
    await state.clear()
    delete_message_id = state_data.get('delete_message_id')
    await bot.delete_message(message_id=delete_message_id, chat_id=message.from_user.id)
    await users_repository.update_context_by_user_id(user_id=message.from_user.id, user_context=message.text)
    await message.answer("Отлично, твой контекст сохранен!")



@standard_router.message(F.text)
@is_channel_subscriber
async def standard_message_handler(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    text = message.text
    user_id = message.from_user.id
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        try:
            ai_answer = await get_current_assistant().send_message(user_id=user_id,
                                                         thread_id=user.standard_ai_threat_id,
                                                         text=text,
                                                         user_data=user)
        except NoSubscription:
            return
        except NoGenerations:
            return
    
    # Используем новую функцию для обработки ответа
    await process_ai_response(
        ai_response=ai_answer,
        message=message,
        user_id=user_id,
        bot=bot,
        request_text=text
    )



@standard_router.message(
    F.media_group_id,                 # только альбомы
    F.content_type == "photo"         # фотографии
)

@media_group_handler   # собираем в список
@is_channel_subscriber
async def handle_photo_album(messages: list[types.Message], state: FSMContext, bot: Bot):
    await state.clear()
    first = messages[0]
    user_id = first.from_user.id
    await bot.send_chat_action(chat_id=first.chat.id, action="typing")
    user = await users_repository.get_user_by_user_id(user_id=user_id)

    # Общий caption Telegram присылает только в первом элементе альбома 
    text = "\n".join([message.caption for message in messages if message.caption is not None])
    # print(text)
    # Скачиваем все фото → BytesIO
    image_buffers: list[io.BytesIO] = []
    photo_ids: list[str] = []
    messages.sort(key=lambda x: x.message_id)
    for msg in messages:
        buf = io.BytesIO()
        await bot.download(msg.photo[-1], destination=buf)
        image_buffers.append(buf)
        photo_ids.append(msg.photo[-1].file_id)
        # print(msg.photo[-1].file_id)
    await users_repository.update_last_photo_id_by_user_id(photo_id=", ".join(photo_ids), user_id=user_id)
    # Отправляем весь список в GPT
    async with ChatActionSender.typing(bot=bot, chat_id=first.chat.id):
        # await bot.send_chat_action(chat_id=first.chat.id, action="typing")
        # photo_answer = await gemini_images_client.generate_gemini_image(prompt=text,
        #                                            reference_images=[image_buffer.read() for image_buffer in image_buffers],)
        # photo = BufferedInputFile(file=photo_answer, filename="image.png")
        # await first.answer_photo(photo=photo)
        try:
            ai_answer = await get_current_assistant().send_message(
                user_id=user_id,
                thread_id=user.standard_ai_threat_id,
                text=text,
                user_data=user,
                image_bytes=image_buffers,
            )
        except NoSubscription:
            return
        except NoGenerations:
            return

        # Используем новую функцию для обработки ответа
        await process_ai_response(
            ai_response=ai_answer,
            message=first,
            user_id=user_id,
            bot=bot,
            request_text=first.caption,
            photo_id=", ".join(photo_ids),
            has_photo=True
        )



@standard_router.message(F.photo)
@is_channel_subscriber
async def standard_message_photo_handler(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user_id = message.from_user.id
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        text = message.caption
        photo_bytes_io = io.BytesIO()
        photo_id = message.photo[-1].file_id
        await users_repository.update_last_photo_id_by_user_id(photo_id=photo_id, user_id=user_id)
        await bot.download(message.photo[-1], destination=photo_bytes_io)
        # photo_answer = await gemini_images_client.generate_gemini_image(prompt=text,
        #                                            reference_images=photo_bytes_io.read())
        # photo = BufferedInputFile(file=photo_answer, filename="image.png")
        # await message.answer_photo(photo=photo)
        try:
            ai_answer = await get_current_assistant().send_message(user_id=user.user_id,
                                                         thread_id=user.standard_ai_threat_id,
                                                         text=text,
                                                         user_data=user,
                                                         image_bytes=[photo_bytes_io])
        except NoSubscription:
            return
        except NoGenerations:
            return

        # Используем новую функцию для обработки ответа
        await process_ai_response(
            ai_response=ai_answer,
            message=message,
            user_id=user_id,
            bot=bot,
            request_text=message.caption,
            photo_id=photo_id,
            has_photo=True
        )


@standard_router.message(F.voice)
@is_channel_subscriber
@is_subscriber
async def standard_message_voice_handler(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user_id = message.from_user.id
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        audio_bytes_io = io.BytesIO()
        await bot.download(message.voice.file_id, destination=audio_bytes_io)
        # Telegram сообщает mime_type для voice
        mime = getattr(message.voice, "mime_type", None)  # Telegram даёт audio/ogg и т.п.

        try:
            transcribed_audio_text = await get_current_assistant().transcribe_audio(
                audio_bytes=audio_bytes_io,
                language="ru"
            )
        except:
            print(traceback.format_exc())
            await message.answer("Не могу распознать, что в голосовом сообщении, попробуй еще раз")
            return
        # print(transcribed_audio_text)
        try:
            ai_answer = await get_current_assistant().send_message(
                user_id=user_id,
                thread_id=user.standard_ai_threat_id,
                text=transcribed_audio_text,
                user_data=user)
        except NoSubscription:
            return
        except NoGenerations:
            return

        # Используем новую функцию для обработки ответа
        await process_ai_response(
            ai_response=ai_answer,
            message=message,
            user_id=user_id,
            bot=bot,
            request_text=transcribed_audio_text,
            has_audio=True
        )


@standard_router.message(
    F.media_group_id,
    F.content_type == "document"
)
@media_group_handler
@is_channel_subscriber
async def handle_document_album(messages: list[types.Message],  state: FSMContext, bot: Bot,):
    await state.clear()
    first = messages[-1]
    user_id = first.from_user.id
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    await bot.send_chat_action(chat_id=first.chat.id, action="typing")
    text = "\n".join([message.caption or "" for message in messages]) or "Вот прикрепленные мной файлы, изучи их"

    doc_buffers: list[tuple[io.BytesIO, str, str]] = []
    file_ids: list[str] = []


    if any(message.document.file_name.split('.')[-1].lower() in ['jpg', 'jpeg', 'png', "DNG", "gif", "dng"] for message in messages):
        try:
            ai_answer = await get_current_assistant().send_message(
                user_id=user_id,
                thread_id=user.standard_ai_threat_id,
                text=text,
                user_data=user,
                image_bytes=[photo[0] for photo in doc_buffers if photo[2] in ['jpg', 'jpeg', 'png', "DNG", "gif", "dng"]],
                document_bytes=[doc for doc in doc_buffers if doc[2] not in ['jpg', 'jpeg', 'png', "DNG", "gif", "dng"]]
            )
        except NoSubscription:
            return
        except NoGenerations:
            return
    else:
        for msg in messages:
            buf = io.BytesIO()
            await bot.download(msg.document, destination=buf)
            file_name = msg.document.file_name
            # print(file_name)
            ext = file_name.split('.')[-1].lower()
            if ext not in SUPPORTED_TEXT_FILE_TYPES:
                await first.reply(
                    f"⚠️ Формат файла «{msg.document.file_name}» не поддерживается. "
                    f"Пришлите один из форматов: {', '.join(sorted(SUPPORTED_TEXT_FILE_TYPES))}"
                )
                return
            doc_buffers.append((buf, file_name, ext))
            file_ids.append(msg.document.file_id)
        try:
            ai_answer = await get_current_assistant().send_message(
                user_id=user_id,
                thread_id=user.standard_ai_threat_id,
                text=text,
                user_data=user,
                document_bytes=doc_buffers
            )
        except NoSubscription:
            return
        except NoGenerations:
            return
    
    # Используем новую функцию для обработки ответа
    await process_ai_response(
        ai_response=ai_answer,
        message=first,
        user_id=user_id,
        bot=bot,
        request_text=text,
        has_files=True,
        file_id=", ".join(file_ids)
    )



@standard_router.message(F.document, F.media_group_id.is_(None))
@is_channel_subscriber
@is_subscriber
async def standard_message_document_handler(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user_id = message.from_user.id
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
        # delete_message = await message.reply("Формулирую ответ, это займет не более 5 секунд")
        text = message.caption
        # print(text)
        buf = io.BytesIO()
        file_id = message.document.file_id
        # print(file_id)
        await bot.download(message.document.file_id, destination=buf)


        file_name = message.document.file_name
        ext = file_name.split('.')[-1].lower()

        # print("slkdjfslkdjfklsdf")
        if message.document.file_name:
            # Получаем расширение из имени файла
            extension = message.document.file_name.split('.')[-1].lower()
            if extension in ['jpg', 'jpeg', 'png', "DNG", "gif", "dng"]:
                await users_repository.update_last_photo_id_by_user_id(photo_id=message.document.file_id, user_id=user_id)
                try:
                    ai_answer = await get_current_assistant().send_message(user_id=user_id,
                                                                 thread_id=user.standard_ai_threat_id,
                                                                 text=text,
                                                                 user_data=user,
                                                                 image_bytes=[buf])
                except NoSubscription:
                    return
                except NoGenerations:
                    return
            else:
                if ext not in SUPPORTED_TEXT_FILE_TYPES:
                    await message.reply(
                        f"⚠️ Формат файла «{message.document.file_name}» не поддерживается. "
                        f"Пришлите один из форматов: {', '.join(sorted(SUPPORTED_TEXT_FILE_TYPES))}"
                    )
                    return
                try:
                    ai_answer = await get_current_assistant().send_message(user_id=user_id,
                                                                 thread_id=user.standard_ai_threat_id,
                                                                 text=text,
                                                                 user_data=user,
                                                                 document_bytes=[(buf, file_name, ext)],
                                                                 document_type=extension)
                    # print(ai_answer)
                except NoSubscription:
                    return
                except NoGenerations:
                    return

            # Используем новую функцию для обработки ответа
            await process_ai_response(
                ai_response=ai_answer,
                message=message,
                user_id=user_id,
                bot=bot,
                request_text=message.caption,
                has_files=True,
                file_id=message.document.file_id
            )





