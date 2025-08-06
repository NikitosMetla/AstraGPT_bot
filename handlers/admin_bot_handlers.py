import asyncio
import io
import traceback

from aiogram import Router, types, Bot, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import any_state
from aiogram.types import InlineKeyboardButton, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import main_bot
from data.keyboards import admin_keyboard, add_delete_admin, cancel_keyboard, back_to_bots_keyboard, \
    db_tables_keyboard, type_users_mailing_keyboard, statistics_keyboard, confirm_send_mailing
from db.repository import admin_repository, users_repository, ai_requests_repository, subscriptions_repository, \
    referral_system_repository, events_repository
from settings import InputMessage, business_connection_id
from utils.generate_promo import generate_single_promo_code
from utils.get_table_db_to_excel import export_table_to_memory
from utils.is_main_admin import is_main_admin
from utils.list_admins_keyboard import Admins_kb

admin_router = Router()


@admin_router.callback_query(F.data=="cancel", any_state)
@is_main_admin
async def admin_cancel(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    await call.message.answer(text="Вы находитесь на стартовой панели, выберите свои дальнейшие действия", reply_markup=admin_keyboard)
    await call.message.delete()


@admin_router.callback_query(F.data.startswith("db_tables|"), any_state)
@is_main_admin
async def choice_table_db(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    table_name = call.data.split("|")[1]
    await state.clear()
    db_table = export_table_to_memory(table_name=table_name)
    if db_table == "Error":
        await call.message.answer("Произошла какая-то ошибка при выгрузке данной таблицы, попробуйте еще раз")
        return
    await call.message.answer_document(document=BufferedInputFile(file=db_table,
                                                               filename=f"{table_name}.xlsx"))


@admin_router.message(F.text=="/start", any_state)
@is_main_admin
async def admin_start(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear()
    await message.delete()
    await message.answer(text="Это Админ бот. С помощью него вы можете получать статистику,"
                              " а также делать дополнительные рассылки по пользователям🤖", reply_markup=admin_keyboard)


@admin_router.message(F.text=="Сделать рассылку")
@is_main_admin
async def new_mailing(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear()
    await message.answer("Выбери тип пользователей, по которым хочешь сделать рассылку",
                         reply_markup=type_users_mailing_keyboard.as_markup())


@admin_router.message(F.text=="Статистика")
@is_main_admin
async def get_statistics(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear()
    await message.answer("Выбери раздел, статистику которого ты хочешь посмотреть",
                         reply_markup=statistics_keyboard.as_markup())


@admin_router.callback_query(F.data.startswith("statistics"), any_state)
@is_main_admin
async def enter_type_users_for_mailing(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    type_statistics = call.data.split("|")[1]
    await state.clear()
    text_message = ""
    if type_statistics == "active_users":
        active_users_stat = await events_repository.get_users_event_stats()
        print(active_users_stat)
        text_message = (f"Количество активных пользователей:\n\n"
                        f"Статистика за час: <b>{active_users_stat.get('hour')}</b>\n"
                        f"Статистика за день: <b>{active_users_stat.get('day')}</b>\n"
                        f"Статистика за неделю: <b>{active_users_stat.get('week')}</b>\n"
                        f"Статистика за месяц: <b>{active_users_stat.get('month')}</b>\n"
                        f"Статистика за квартал: <b>{active_users_stat.get('quarter')}</b>\n")
    elif type_statistics == "users":
        user_stat = await users_repository.get_user_creation_statistics()
        text_message = (f"Количество новых пользователей:\n\n"
                        f"Статистика за день: <b>{user_stat.get('day')}</b>\n"
                        f"Статистика за неделю: <b>{user_stat.get('week')}</b>\n"
                        f"Статистика за месяц: <b>{user_stat.get('month')}</b>\n"
                        f"Статистика за квартал: <b>{user_stat.get('quarter')}</b>\n"
                        f"Статистика за все время <b>{user_stat.get('all_time')}</b>")
    elif type_statistics == "gpt":
        ai_stat = await ai_requests_repository.get_ai_requests_statistics()
        text_message = (
            "Статистика по запросам к GPT (без аудио):\n\n"
            f"За день:\n"
            f"   Всего запросов: <b>{ai_stat['day']['total']}</b>\n"
            f"   С фото: <b>{ai_stat['day']['with_photo']}</b>\n"
            f"   С файлами: <b>{ai_stat['day']['with_files']}</b>\n\n"
            f"За неделю:\n"
            f"   Всего запросов: <b>{ai_stat['week']['total']}</b>\n"
            f"   С фото: <b>{ai_stat['week']['with_photo']}</b>\n"
            f"   С файлами: <b>{ai_stat['week']['with_files']}</b>\n\n"
            f"За месяц:\n"
            f"   Всего запросов: <b>{ai_stat['month']['total']}</b>\n"
            f"   С фото: <b>{ai_stat['month']['with_photo']}</b>\n"
            f"   С файлами: <b>{ai_stat['month']['with_files']}</b>\n\n"
            f"За квартал:\n"
            f"   Всего запросов: <b>{ai_stat['quarter']['total']}</b>\n"
            f"   С фото: <b>{ai_stat['quarter']['with_photo']}</b>\n"
            f"   С файлами: <b>{ai_stat['quarter']['with_files']}</b>\n\n"
            f"За все время:\n"
            f"   Всего запросов: <b>{ai_stat['all_time']['total']}</b>\n"
            f"   С фото: <b>{ai_stat['all_time']['with_photo']}</b>\n"
            f"   С файлами: <b>{ai_stat['all_time']['with_files']}</b>"
        )
    else:
        sub_stat = await subscriptions_repository.get_active_subscriptions_count()
        text_message = f"Количество пользователей, у которых на данный подписка: <b>{sub_stat}</b>"
    await call.message.answer(text=text_message, parse_mode="HTML")
    await call.message.delete()



@admin_router.callback_query(F.data.startswith("type_users_mailing"), any_state)
@is_main_admin
async def enter_type_users_for_mailing(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    type_users = call.data.split("|")[1]
    if type_users == "all":
        message = await call.message.answer(text="Напиши сообщение, которое ВСЕМ разошлется пользователям",
                                       reply_markup=cancel_keyboard.as_markup())
    elif type_users == "sub":
        message = await call.message.answer(text="Напиши сообщение, которое  разошлется пользователям С ПОДПИСКОЙ",
                                            reply_markup=cancel_keyboard.as_markup())
    else:
        message = await call.message.answer(text="Напиши сообщение, которое разошлется пользователям БЕЗ ПОДПИСКИ",
                                            reply_markup=cancel_keyboard.as_markup())
    await state.set_state(InputMessage.enter_message_mailing)
    await state.update_data(message_id=call.message.message_id, type_users=type_users)



@admin_router.message(F.text=="Выгрузка таблиц")
@is_main_admin
async def get_db_tables(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear()
    message = await message.answer(text="Выбери таблицу, данные которой ты хочешь выгрузить",
                                   reply_markup=db_tables_keyboard.as_markup())


@admin_router.message(F.photo, InputMessage.enter_message_mailing)
async def enter_message_photo_mailing(message: types.Message, state: FSMContext, bot: Bot):
    split_text = message.caption.split("\n")
    state_data = await state.get_data()
    type_users = state_data.get("type_users")
    message_id = state_data.get("message_id")
    photo = message.photo[-1].file_id
    photo_bytes_io = io.BytesIO()
    await bot.download(message.photo[-1], destination=photo_bytes_io)
    print(type_users)
    user = await users_repository.get_user_by_user_id(user_id=message.from_user.id)
    if type_users == "all":
        try:
            # return
            caption = message.caption
            if "with usernames" in caption:
                caption = f"Дорогой {'@' + user.username if user.username else 'друг'}!|||\n\n" + '\n'.join(split_text[1:])
            mailing_message = await message.answer_photo(caption=caption,
                                      photo=BufferedInputFile(file=photo_bytes_io.getvalue(),
                                                              filename="mailing_photo.jpg"),
                                                        reply_markup = confirm_send_mailing().as_markup())
            # await message.answer("Подтвердить рассылку сообщения выше?", ))
        except Exception as e:
            print(e)
    await bot.delete_message(message_id=message_id, chat_id=message.from_user.id)
    await state.clear()


@admin_router.callback_query(F.data.startswith("confirm_send_mailing"), any_state)
@is_main_admin
async def confirm_mailing_message(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    call_data = call.data.split("|")
    is_confirm = True if call_data[1] == "yes" else False
    message = call.message
    split_text = message.caption.split("|||")
    photo_bytes_io = io.BytesIO()
    await bot.download(message.photo[-1], destination=photo_bytes_io)
    if len(split_text) > 1:
        with_usernames = True
    else:
        with_usernames = False
    users = await users_repository.select_all_users()
    if is_confirm:
        await message.answer(text="Начали рассылку по пользователями с твоим отправленным фото")
        await call.message.delete()
        sending_messages = 0
        send_messages = {}
        for user in users:
            caption = message.caption
            if user.user_id == 774127719:
                    # print("send")
                try:
                    if with_usernames:
                        caption = f"Дорогой {'@' + user.username if user.username else 'друг'}!\n" + '\n'.join(split_text[1:])
                    send_message = await main_bot.send_photo(chat_id=user.user_id, caption=caption,
                                              photo=BufferedInputFile(file=photo_bytes_io.getvalue(),
                                                                      filename="mailing_photo.jpg"))
                    send_messages[user.user_id] = send_message.message_id
                    sending_messages += 1
                except Exception as e:
                    print(e)
                    continue
        await message.answer(text=f"Рассылка завершена. {sending_messages} из {len(users)} человек получили рассылку")
        print(send_messages)
    else:
        await call.message.delete()


@admin_router.message(F.text, InputMessage.enter_message_mailing)
@is_main_admin
async def enter_message_mailing(message: types.Message, state: FSMContext, bot: Bot):
    split_text = message.text.split("\n")
    state_data = await state.get_data()
    type_users = state_data.get("type_users")
    message_id = state_data.get("message_id")
    photo = message.photo[-1].file_id
    photo_bytes_io = io.BytesIO()
    await bot.download(message.photo[-1], destination=photo_bytes_io)
    print(type_users)
    user = await users_repository.get_user_by_user_id(user_id=message.from_user.id)
    if type_users == "all":
        try:
            # return
            text = message.text
            if "with usernames" in text:
                text = f"Дорогой {'@' + user.username if user.username else 'друг'}!|||\n\n" + '\n'.join(
                    split_text[1:])
            mailing_message = await message.answer(text=text,
                                                   reply_markup=confirm_send_mailing().as_markup())
            # await message.answer("Подтвердить рассылку сообщения выше?", ))
        except Exception as e:
            print(e)
    await bot.delete_message(message_id=message_id, chat_id=message.from_user.id)
    await state.clear()


@admin_router.message(F.text=="Добавить / удалить админа")
@is_main_admin
async def add_or_delete_admin(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear()
    await message.answer(text="Выберите свои дальнейшие действия", reply_markup=add_delete_admin.as_markup())


@admin_router.callback_query(F.data == "add_admin")
@is_main_admin
async def enter_new_admin_id(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await call.message.edit_text(text="Отлично, теперь введи telegram id нового админа! Учти,"
                                      " что у нового админа должен быть чат с данным ботом",
                                 reply_markup=cancel_keyboard.as_markup())
    await state.set_state(InputMessage.enter_admin_id)


@admin_router.callback_query(F.data == "delete_admin")
@is_main_admin
async def delete_old_admin(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    keyboard = await Admins_kb().generate_list()
    await call.message.edit_text(text="Отлично, теперь выбери из представленных админов, которого хочешь удалить",
                                 reply_markup=keyboard.as_markup())


@admin_router.callback_query(F.data.startswith("admin|"))
@is_main_admin
async def actions_admin(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    admin_id = call.data.split("|")[1]
    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="Удалить админа", callback_data=f"delete|{admin_id}"))
    keyboard.row(InlineKeyboardButton(text="Отмена", callback_data=f"cancel"))
    await call.message.edit_text(text="Выбери свои дальнейшие действия с админом!",
                                 reply_markup=keyboard.as_markup())


@admin_router.callback_query(F.data.startswith("delete|"))
@is_main_admin
async def choice_delete_admin(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    admin_id = call.data.split("|")[1]
    await admin_repository.delete_admin_by_admin_id(int(admin_id))
    await call.message.answer(text=f"Отлично, вы удалили админа с telegram id {admin_id},"
                                   f" выберите свои дальнейшие действия!", reply_markup=admin_keyboard)
    await call.message.delete()


@admin_router.message(F.text, InputMessage.enter_admin_id)
@is_main_admin
async def add_mew_admin(message: types.Message, state: FSMContext, bot: Bot):
    try:
        message_admin = await bot.send_message(chat_id=message.text, text="Вас добавили в данного бота, как админа!")
        await admin_repository.add_admin(admin_id=int(message.text), username=message_admin.chat.username)
        await message.answer(text="Отлично, вы успешно добавили нового админа!", reply_markup=admin_keyboard)
        await message.delete()
        await state.clear()
    except:
        await message.answer(text="Данного telegram id не существует или у нового админа нет чата с ботом, убедитесь"
                                  " в корректности данных и попробуйте снова!",
                             reply_markup=cancel_keyboard.as_markup())


@admin_router.message(F.text=="Сгенерировать промокод")
@is_main_admin
async def get_statistics(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear()
    await state.set_state(InputMessage.enter_promo_days)
    await message.answer("Пожалуйста, введи количество дней, которое будет давать активация данного промокода",
                         reply_markup=cancel_keyboard.as_markup())


@admin_router.message(F.text, InputMessage.enter_promo_days)
@is_main_admin
async def get_statistics(message: types.Message, state: FSMContext, bot: Bot):
    max_days = message.text
    if max_days.isdigit():
        await state.clear()
        await message.answer("Отлично, теперь введи максимальное количество активаций данного промокода",
                             reply_markup=cancel_keyboard.as_markup())
        await state.set_state(InputMessage.enter_max_activations_promo)
        await state.update_data(max_days=max_days)
        return
    await message.answer("Ты ввел не число, попробуй еще раз ввести количество дней,"
                         " которое будет давать активация данного промокода",
                         reply_markup=cancel_keyboard.as_markup())


@admin_router.message(F.text, InputMessage.enter_max_activations_promo)
@is_main_admin
async def get_statistics(message: types.Message, state: FSMContext, bot: Bot):
    max_activations = message.text
    state_data = await state.get_data()
    max_days = int(state_data.get("max_days"))
    if max_activations.isdigit():
        max_activations = int(max_activations)
        await state.clear()
        promo_code = await generate_single_promo_code()
        await referral_system_repository.add_promo(promo_code=promo_code,
                                                   max_days=max_days,
                                                   max_activations=max_activations,
                                                   type_promo="from_admin")
        await message.answer(f"Отлично, ты выпустил промокод!\n\nПромокод: <code>{promo_code}</code>")
        return
    await message.answer("Ты ввел не число, попробуй еще раз ввести"
                         " максимальное количество активаций данного промокода",
                         reply_markup=cancel_keyboard.as_markup())
