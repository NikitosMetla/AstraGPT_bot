import io
import pprint
import traceback

from aiogram import Router, F, Bot, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import any_state
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InputMediaPhoto
from aiogram_media_group import media_group_handler

from data.keyboards import profiles_keyboard, cancel_keyboard, settings_keyboard, \
    confirm_clear_context, buy_sub_keyboard, subscriptions_keyboard, delete_payment_keyboard, unlink_card_keyboard
from db.repository import users_repository, ai_requests_repository, subscriptions_repository
from settings import InputMessage, photos_pages, OPENAI_ALLOWED_DOC_EXTS, gpt_assistant
from utils.paginator import MechanicsPaginator
from utils.parse_gpt_text import split_telegram_html, sanitize_with_links

standard_router = Router()


@standard_router.callback_query(F.data == "delete_payment", any_state)
@standard_router.message(F.text == "/unlink_card", any_state)
async def sub_message(message: Message | CallbackQuery, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
    if type(message) == Message:
        if user_sub is None:
            await message.answer("✨Дорогой друг, на данный момент у тебя нет активной подписки и привязанной карты в частности")
            return
        await message.answer("Ты уверен, что хочешь отвязать карту для оплаты подписки? После этого"
                             " твоя подписка не сможет автоматически продлеваться",
                             reply_markup=unlink_card_keyboard.as_markup())
    else:
        if user_sub is None:
            await message.message.answer("✨Дорогой друг, на данный момент у тебя нет активной подписки и привязанной карты в частности")
            return
        await message.message.delete()
        await message.message.answer("Ты уверен, что хочешь отвязать карту для оплаты подписки? После этого"
                             " твоя подписка не сможет автоматически продлеваться",
                             reply_markup=unlink_card_keyboard.as_markup())


@standard_router.callback_query(F.data == "unlink_card", any_state)
async def sub_message(call: CallbackQuery, state: FSMContext, bot: Bot):
    user_id = call.from_user.id
    user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
    if user_sub is None or user_sub.plan_name == "Free":
        await call.message.answer(
            "✨Дорогой друг, на данный момент у тебя нет активной подписки и привязанной карты в частности")
        return
    if user_sub.method_id is None:
        await call.message.answer(
            "✨Дорогой друг, на данный момент у тебя уже не привязана никакая карта")
        return
    await subscriptions_repository.delete_payment_method(subscription_id=user_sub.id)
    await call.message.delete()
    await call.message.answer("Отлично, отвязали твой метод оплаты. Теперь твоя подписка не сможет продлеваться автоматически")


@standard_router.message(F.text == "/subscribe", any_state)
async def sub_message(message: Message, state: FSMContext, bot: Bot):
    user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=message.from_user.id)
    if user_sub is not None:
        await message.answer("""🔓 Откройте весь потенциал нашего ИИ-бота — оформите подписку прямо здесь.
    
    Тарифы
    • Smart — 499 ₽/мес: неограниченный доступ к модели GPT-4o-mini (до 1 000 сообщений).
    • Pro — 999 ₽/мес: приоритетный канал к GPT-4o и безлимитные запросы, а также модель для генерации изображений gpt-image-1.
    
    📅 Подписка активируется мгновенно, отменить можно в любой момент.
    
    😊 Выберите подходящий уровень и нажмите «Оплатить» — мы уже готовы помочь!""",
                             reply_markup=buy_sub_keyboard.as_markup())
    else:
        await message.answer("Дорогой друг, на данный момент у тебя подключена стандартная подписка."
                             " Если ты хочешь отвязать карту, то нажми на кнопку ниже",
                             reply_markup=delete_payment_keyboard.as_markup())


@standard_router.callback_query(F.data == "buy_sub")
async def choice_sub_message(call: CallbackQuery, state: FSMContext):
    await call.message.delete()
    await call.message.answer("""Выбери тип подписки, которую хочешь приобрести:
Тарифы
    • Smart — 499 ₽/мес: неограниченный доступ к модели GPT-4o-mini (до 1 000 сообщений).
    • Pro — 999 ₽/мес: приоритетный канал к GPT-4o и безлимитные запросы, а также модель для генерации изображений gpt-image-1.""",
                              reply_markup=subscriptions_keyboard.as_markup())



@standard_router.callback_query(F.data.startswith("mechanics_paginator"))
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
async def send_user_message(message: Message, state: FSMContext, bot: Bot, user_data):
    paginator = MechanicsPaginator(page_now=1)
    keyboard = paginator.generate_now_page()
    await message.answer_photo(photo=photos_pages.get(paginator.page_now),
                               reply_markup=keyboard)


@standard_router.message(F.text == "/profile", any_state)
async def send_user_message(message: Message, state: FSMContext, bot: Bot):
    await message.answer('👤 Твой профиль\n\n✓ Подписка: Активна ∞ (без ограничений)\n✓ Доступ: Полный'
                         ' ко всем функциям\n\n✨ Персонализация\nХочешь идеальные ответы? Расскажи о себе в '
                         '"Настройке контекста"! Бот учтёт это например при:\n- Составлении резюме\n- '
                         'Написании персональных текстов\n- Даче индивидуальных рекомендаций\n\nЧем больше знает бот — тем точнее помогает!',
                         reply_markup=profiles_keyboard.as_markup())


@standard_router.message(F.text == "/clear_context", any_state)
async def send_user_message(message: Message, state: FSMContext, bot: Bot):
    await message.answer('Ты уверен, что хочешь очистить контекст данного диалога?',
                         reply_markup=confirm_clear_context.as_markup())

@standard_router.callback_query(F.data == "clear_context", any_state)
async def send_user_message(call: CallbackQuery, state: FSMContext, bot: Bot):
    user_id = call.from_user.id
    await users_repository.update_thread_id_by_user_id(user_id=user_id, thread_id=None)
    await call.message.delete()
    await call.message.answer("Контекст твоего диалога очищен✨")

@standard_router.callback_query(F.data == "not_clear_context", any_state)
async def send_user_message(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.message.delete()


@standard_router.message(F.text == "/settings", any_state)
async def send_user_message(message: Message, state: FSMContext, bot: Bot):
    await message.answer('👤 🤖 Выбери режим работы\n\n• Универсальный — быстрые ответы на повседневные'
                         ' вопросы 😎\n• Специализированный — анализ данных, код и сложные запросы 🧠\n\nПросто'
                         ' нажми на нужный вариант — и мы сразу поможем!',
                         reply_markup=settings_keyboard.as_markup())


@standard_router.callback_query(F.data == "edit_user_context", any_state)
async def send_user_message(call: CallbackQuery, state: FSMContext, bot: Bot):
    user = await users_repository.get_user_by_user_id(user_id=call.from_user.id)
    delete_message = await call.message.answer(f"AstraGPT запомнит всю информацию, которую вы сейчас"
                              f" введете и будет учитывать ее при составление ответов для вас!\n\nВаш нынешний контекст:\n{user.context}",
                              reply_markup=cancel_keyboard.as_markup())
    await state.set_state(InputMessage.enter_user_context_state)
    await call.message.delete()
    await state.update_data(delete_message_id=delete_message.message_id)


@standard_router.callback_query(F.data.startswith("mode|"), any_state)
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
        await users_repository.update_model_type_by_user_id(model_type="gpt-4.1-nano", user_id=call.from_user.id)
        pin_message = await call.message.answer("Активная модель - 🤖Универсальная")
    else:
        await users_repository.update_model_type_by_user_id(model_type="gpt-4.1", user_id=call.from_user.id)
        pin_message = await call.message.answer("Активная модель - 🧠Специализированная")
    await pin_message.pin()
    await call.message.delete()


@standard_router.callback_query(F.data == "cancel", any_state)
async def send_user_message(call: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    await call.message.delete()


@standard_router.message(F.text, InputMessage.enter_user_context_state)
async def standard_message_handler(message: Message, state: FSMContext, bot: Bot):
    state_data = await state.get_data()
    await state.clear()
    delete_message_id = state_data.get('delete_message_id')
    await bot.delete_message(message_id=delete_message_id, chat_id=message.from_user.id)
    await users_repository.update_context_by_user_id(user_id=message.from_user.id, user_context=message.text)
    await message.answer("Отлично, твой контекст сохранен!")



@standard_router.message(F.text)
async def standard_message_handler(message: Message, bot: Bot):
    text = message.text
    user_id = message.from_user.id
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    # if user is not None and user.full_registration:
    # user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
    # if user_sub is None:
    #     await message.answer("Чтобы общаться со стандартным GPT у тебя должна быть подписка",
    #                          reply_markup=buy_sub_keyboard.as_markup())
    #     return
    # delete_message = await message.reply("Формулирую ответ, это займет не более 5 секунд")
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    ai_answer = await gpt_assistant.send_message(user_id=user_id,
                                                 thread_id=user.standard_ai_threat_id,
                                                 text=text,
                                                 user_data=user)
    images = []
    if type(ai_answer) == dict and ai_answer.get("filename"):
        try:
            await message.reply_document(document=BufferedInputFile(file=ai_answer.get("bytes"),
                                                                     filename=ai_answer.get("filename")))
            ai_answer = "🤖Сгенерированный файл"
        except:
            print(traceback.format_exc())
            await message.answer("Возникла ошибка при отправке файла, попробуй еще раз")
            return
    elif type(ai_answer) == dict:
        images = ai_answer.get("images")
        ai_answer = ai_answer.get("text")

    # print(ai_answer)
    ai_answer = sanitize_with_links(ai_answer)
    # pprint.pprint(ai_answer)
    # print(ai_answer)
    await ai_requests_repository.add_request(user_id=user.user_id,
                                             answer_ai=ai_answer if ai_answer is not None and ai_answer != "" else "Выдал файл или фото",
                                             user_question=text,
                                             generate_images=True if len(images) > 0 else False
                                             )
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    from aiogram.enums import ParseMode
    if len(images) == 0:
        split_messages = split_telegram_html(ai_answer)
        print("\n\n")
        # pprint.pprint(split_messages)
        for chunk in split_messages:
            await message.reply(
                chunk,
                disable_web_page_preview=True,
                parse_mode=ParseMode.HTML
            )
        return
    else:
        raw = images[0]
        buffer = io.BytesIO(raw)
        buffer.seek(0)

        photo = BufferedInputFile(file=buffer.getvalue(), filename="image.png")
        message = await message.reply_photo(text=ai_answer,
            parse_mode=ParseMode.HTML,  # ← ключевой параметр
            disable_web_page_preview=True,
            photo=photo) # чтобы не появлялись лишние превью
        await users_repository.update_last_photo_id_by_user_id(photo_id=message.photo[-1].file_id, user_id=user_id)



@standard_router.message(
    F.media_group_id,                 # только альбомы
    F.content_type == "photo"         # фотографии
)
@media_group_handler                  # собираем в список
async def handle_photo_album(messages: list[types.Message], bot: Bot):
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
    for msg in messages:
        buf = io.BytesIO()
        await bot.download(msg.photo[-1], destination=buf)
        image_buffers.append(buf)
        photo_ids.append(msg.photo[-1].file_id)
        print(msg.photo[-1].file_id)
    await users_repository.update_last_photo_id_by_user_id(photo_id=", ".join(photo_ids), user_id=user_id)
    # Отправляем весь список в GPT
    await bot.send_chat_action(chat_id=first.chat.id, action="typing")
    ai_answer = await gpt_assistant.send_message(
        user_id=user_id,
        thread_id=user.standard_ai_threat_id,
        text=text,
        user_data=user,
        image_bytes=image_buffers,
    )

    images = []
    if type(ai_answer) == dict and ai_answer.get("filename"):
        try:
            await first.reply_document(document=BufferedInputFile(file=ai_answer.get("bytes"),
                                                                    filename=ai_answer.get("filename")))
            ai_answer = "🤖Сгенерированный файл"
        except:
            print(traceback.format_exc())
            await first.answer("Возникла ошибка при отправке файла, попробуй еще раз")
            return
    elif type(ai_answer) == dict:
        images = ai_answer.get("images")
        ai_answer = ai_answer.get("text")
    # ai_answer = sanitize_with_links(ai_answer)
    from aiogram.enums import ParseMode
    if len(images) == 0:
        for chunk in split_telegram_html(ai_answer):
            await first.reply(
                chunk,

                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        return
    else:
        raw = images[0]
        buffer = io.BytesIO(raw)
        buffer.seek(0)

        photo = BufferedInputFile(file=buffer.getvalue(), filename="image.png")
        message = await messages[0].reply_photo(text=ai_answer,
                                            parse_mode=ParseMode.HTML,  # ← ключевой параметр
                                            disable_web_page_preview=True,
                                            photo=photo)  # чтобы не появлялись лишние превью
    await ai_requests_repository.add_request(user_id=user.user_id,
                                             has_photo=True,
                                             answer_ai=ai_answer if ai_answer is not None and ai_answer != "" else "Выдал фото или видел",
                                             user_question=first.caption,
                                             photo_id=", ".join(photo_ids),
                                             generate_images=True if len(images) > 0 else False)



@standard_router.message(F.photo)
async def standard_message_photo_handler(message: Message, bot: Bot):
    user_id = message.from_user.id
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    # user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
    # if user_sub is None:
    #     await message.answer("Чтобы общаться со стандартным GPT у тебя должна быть подписка",
    #                          reply_markup=buy_sub_keyboard.as_markup())
    #     return
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    text = message.caption
    photo_bytes_io = io.BytesIO()
    photo_id = message.photo[-1].file_id
    print(photo_id)
    await users_repository.update_last_photo_id_by_user_id(photo_id=photo_id, user_id=user_id)
    # print(photo_id)
    await bot.download(message.photo[-1], destination=photo_bytes_io)
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    # try:
    #     ai_photo = await generate_image_bytes(prompt=message.caption, images=[photo_bytes_io.getvalue()])
    #     await message.answer_photo(BufferedInputFile(file=ai_photo, filename="image.png"))
    # except Exception as e:
    #     await message.answer("ошибка")
    # print()
    ai_answer = await gpt_assistant.send_message(user_id=user.user_id,
                                                 thread_id=user.standard_ai_threat_id,
                                                 text=text,
                                                 user_data=user,
                                                 image_bytes=[photo_bytes_io])
    images = []
    if type(ai_answer) == dict and ai_answer.get("filename"):
        try:
            await message.reply_document(document=BufferedInputFile(file=ai_answer.get("bytes"),
                                                                    filename=ai_answer.get("filename")))
            ai_answer = "🤖Сгенерированный файл"
        except:
            print(traceback.format_exc())
            await message.answer("Возникла ошибка при отправке файла, попробуй еще раз")
            return
    elif type(ai_answer) == dict:
        images = ai_answer.get("images")
        ai_answer = ai_answer.get("text")
    # ai_answer = sanitize_with_links(ai_answer)
    from aiogram.enums import ParseMode
    if len(images) == 0:
        for chunk in split_telegram_html(ai_answer):
            await message.reply(
                chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
    else:
        raw = images[0]
        buffer = io.BytesIO(raw)
        buffer.seek(0)

        photo = BufferedInputFile(file=buffer.getvalue(), filename="image.png")
        message = await message.reply_photo(text=ai_answer,
                                            parse_mode=ParseMode.HTML,  # ← ключевой параметр
                                            disable_web_page_preview=True,
                                            photo=photo)  # чтобы не появлялись лишние превью
        await users_repository.update_last_photo_id_by_user_id(photo_id=message.photo[-1].file_id, user_id=user_id)
    await ai_requests_repository.add_request(user_id=user.user_id,
                                             has_photo=True,
                                             photo_id=photo_id,
                                             answer_ai=ai_answer if ai_answer is not None and ai_answer != "" else "Выдал фото или файл",
                                             user_question=message.caption,
                                             generate_images=True if len(images) > 0 else False)


@standard_router.message(F.voice)
async def standard_message_voice_handler(message: Message, bot: Bot):
    user_id = message.from_user.id
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    # if user is not None and user.full_registration:
    # user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
    # if user_sub is None:
    #     await message.answer("Чтобы общаться со стандартным GPT у тебя должна быть подписка",
    #                          reply_markup=buy_sub_keyboard.as_markup())
    #     return
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    audio_bytes_io = io.BytesIO()
    message_voice_id = message.voice.file_id
    await bot.download(message_voice_id, destination=audio_bytes_io)
    try:
        transcribed_audio_text = await gpt_assistant.transcribe_audio(audio_bytes=audio_bytes_io)
    except:
        await message.answer("Не могу распознать, что в голосовом сообщении, попробуй еще раз")
        return
    # print(transcribed_audio_text)
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    ai_answer = await gpt_assistant.send_message(
        user_id=user_id,
        thread_id=user.standard_ai_threat_id,
        text=transcribed_audio_text,
        user_data=user)
    images = []
    if type(ai_answer) == dict and ai_answer.get("filename"):
        try:
            await message.reply_document(document=BufferedInputFile(file=ai_answer.get("bytes"),
                                                                    filename=ai_answer.get("filename")))
            ai_answer = "🤖Сгенерированный файл"
        except:
            print(traceback.format_exc())
            await message.answer("Возникла ошибка при отправке файла, попробуй еще раз")
            return
    elif type(ai_answer) == dict:
        images = ai_answer.get("images")
        ai_answer = ai_answer.get("text")
    # ai_answer = sanitize_with_links(ai_answer)
    from aiogram.enums import ParseMode
    if len(images) == 0:
        for chunk in split_telegram_html(ai_answer):
            await message.reply(
                chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
    else:
        raw = images[0]
        buffer = io.BytesIO(raw)
        buffer.seek(0)

        photo = BufferedInputFile(file=buffer.getvalue(), filename="image.png")
        message = await message.reply_photo(text=ai_answer,
                                            parse_mode=ParseMode.HTML,  # ← ключевой параметр
                                            disable_web_page_preview=True,
                                            photo=photo)  # чтобы не появлялись лишние превью
        await users_repository.update_last_photo_id_by_user_id(photo_id=message.photo[-1].file_id, user_id=user_id)
    await ai_requests_repository.add_request(user_id=user.user_id,
                                             has_audio=True,
                                             answer_ai=ai_answer if ai_answer is not None and type(ai_answer) == str and ai_answer != ""  else "Выдал фото или файл",
                                             user_question=transcribed_audio_text,
                                             generate_images=True if len(images) > 0 else False)


@standard_router.message(
    F.media_group_id,
    F.content_type == "document"
)
@media_group_handler
async def handle_document_album(messages: list[types.Message], bot: Bot):
    first = messages[-1]
    user_id = first.from_user.id
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    await bot.send_chat_action(chat_id=first.chat.id, action="typing")
    text = "\n".join([message.caption or "" for message in messages]) or "Вот прикрепленные мной файлы, изучи их"

    doc_buffers: list[tuple[io.BytesIO, str, str]] = []
    file_ids: list[str] = []

    for msg in messages:
        buf = io.BytesIO()
        await bot.download(msg.document, destination=buf)
        file_name = msg.document.file_name
        print(file_name)
        ext = file_name.split('.')[-1].lower()
        if ext not in OPENAI_ALLOWED_DOC_EXTS:
            await first.reply(
                f"⚠️ Формат файла «{msg.document.file_name}» не поддерживается. "
                f"Пришлите один из форматов: {', '.join(sorted(OPENAI_ALLOWED_DOC_EXTS))}"
            )
            return
        doc_buffers.append((buf, file_name, ext))
        file_ids.append(msg.document.file_id)
    if any(message.document.file_name.split('.')[-1].lower() in ['jpg', 'jpeg', 'png', "DNG", "gif", "dng"] for message in messages):
        ai_answer = await gpt_assistant.send_message(
            user_id=user_id,
            thread_id=user.standard_ai_threat_id,
            text=text,
            user_data=user,
            image_bytes=[photo[0] for photo in doc_buffers if photo[2] in ['jpg', 'jpeg', 'png', "DNG", "gif", "dng"]],
            document_bytes=[doc for doc in doc_buffers if doc[2] not in ['jpg', 'jpeg', 'png', "DNG", "gif", "dng"]]
        )
    else:
        ai_answer = await gpt_assistant.send_message(
            user_id=user_id,
            thread_id=user.standard_ai_threat_id,
            text=text,
            user_data=user,
            document_bytes=doc_buffers
        )
    images = []
    if type(ai_answer) == dict and ai_answer.get("filename"):
        try:
            await first.reply_document(caption="🤖Сгенерированный файл", document=BufferedInputFile(file=ai_answer.get("bytes"),
                                                                    filename=ai_answer.get("filename")))
            ai_answer = "🤖Сгенерированный файл"
        except:
            print(traceback.format_exc())
            await first.answer("Возникла ошибка при отправке файла, попробуй еще раз")
            return
    elif type(ai_answer) == dict:
        images = ai_answer.get("images")
        ai_answer = ai_answer.get("text")
    # print(ai_answer)
    # ai_answer = sanitize_with_links(ai_answer)
    from aiogram.enums import ParseMode
    if len(images) == 0:
        for chunk in split_telegram_html(ai_answer):
            await first.reply(
                chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
    else:
        raw = images[0]
        buffer = io.BytesIO(raw)
        buffer.seek(0)

        photo = BufferedInputFile(file=buffer.getvalue(), filename="image.png")
        message = await first.reply_photo(text=ai_answer,
                                            parse_mode=ParseMode.HTML,  # ← ключевой параметр
                                            disable_web_page_preview=True,
                                            photo=photo)  # чтобы не появлялись лишние превью
        await users_repository.update_last_photo_id_by_user_id(photo_id=message.photo[-1].file_id, user_id=user_id)
    await ai_requests_repository.add_request(
        user_id=user.user_id,
        has_files=True,
        file_id=", ".join(file_ids),
        answer_ai=ai_answer,
        user_question=text,
        generate_images=True if len(images) > 0 else False
    )



@standard_router.message(F.document, F.media_group_id.is_(None))
async def standard_message_document_handler(message: Message, bot: Bot):
    user_id = message.from_user.id
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    # if user is not None and user.full_registration:
    # user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
    # if user_sub is None:
    #     await message.answer("Чтобы общаться со стандартным GPT у тебя должна быть подписка",
    #                          reply_markup=buy_sub_keyboard.as_markup())
    #     return
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    # delete_message = await message.reply("Формулирую ответ, это займет не более 5 секунд")
    text = message.caption
    buf = io.BytesIO()
    await bot.download(message.document, destination=buf)
    file_name = message.document.file_name
    # print(file_name)
    ext = file_name.split('.')[-1].lower()
    if ext not in OPENAI_ALLOWED_DOC_EXTS:
        await message.reply(
            f"⚠️ Формат файла «{message.document.file_name}» не поддерживается. "
            f"Пришлите один из форматов: {', '.join(sorted(OPENAI_ALLOWED_DOC_EXTS))}"
        )
        return
    if message.document.file_name:
        # Получаем расширение из имени файла
        extension = message.document.file_name.split('.')[-1].lower()
        if extension in ['jpg', 'jpeg', 'png', "DNG", "gif", "dng"]:
            await users_repository.update_last_photo_id_by_user_id(photo_id=message.document.file_id, user_id=user_id)
            ai_answer = await gpt_assistant.send_message(user_id=user_id,
                                                         thread_id=user.standard_ai_threat_id,
                                                         text=text,
                                                         user_data=user,
                                                         image_bytes=[buf])
        else:
            ai_answer = await gpt_assistant.send_message(user_id=user_id,
                                                         thread_id=user.standard_ai_threat_id,
                                                         text=text,
                                                         user_data=user,
                                                         document_bytes=[(buf, file_name, ext)],
                                                         document_type=extension)
        images = []
        if type(ai_answer) == dict and ai_answer.get("filename"):
            try:
                await message.reply_document(document=BufferedInputFile(file=ai_answer.get("bytes"),
                                                                      filename=ai_answer.get("filename")))
                ai_answer = "🤖Сгенерированный файл"
            except:
                print(traceback.format_exc())
                await message.answer("Возникла ошибка при отправке файла, попробуй еще раз")
                return
        elif type(ai_answer) == dict:
            images = ai_answer.get("images")
            ai_answer = ai_answer.get("text")
        # print(ai_answer)
        # ai_answer = sanitize_with_links(ai_answer)
        from aiogram.enums import ParseMode
        if len(images) == 0:
            for chunk in split_telegram_html(ai_answer):
                await message.reply(
                    chunk,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
        else:
            # print("sdgsf")
            raw = images[0]
            buffer = io.BytesIO(raw)
            buffer.seek(0)

            photo = BufferedInputFile(file=buffer.getvalue(), filename="image.png")
            message = await message.reply_photo(caption=ai_answer,
                                                parse_mode=ParseMode.HTML,  # ← ключевой параметр
                                                disable_web_page_preview=True,
                                                photo=photo)  # чтобы не появлялись лишние превью
            await users_repository.update_last_photo_id_by_user_id(photo_id=message.photo[-1].file_id, user_id=user_id)
        await ai_requests_repository.add_request(user_id=user.user_id,
                                                 answer_ai=ai_answer if ai_answer is not None and ai_answer != "" and type(
                                                     ai_answer) == str else "Выдал фото или файл",
                                                 user_question=message.caption,
                                                 has_files=True,
                                                 file_id=message.document.file_id
                                                 )


#


