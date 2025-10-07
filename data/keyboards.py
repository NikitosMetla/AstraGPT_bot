from aiogram.types import InlineKeyboardButton, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

table_names = [
    "admins",
    "ai_requests",
    "events",
    "operations",
    "promo_activations",
    "referral_system",
    "subscriptions",
    "users",
    "notifications"
]

# def call_manager_keyboard(user_id, username: str):
#     keyboard = InlineKeyboardBuilder()
#     keyboard.row(InlineKeyboardButton(text="Позвать менеджера?", callback_data=f"call_manager|{user_id}|{username}"))
#     return keyboard

admin_kb = [
        [KeyboardButton(text='Статистика'), KeyboardButton(text='Выгрузка таблиц')],
        [KeyboardButton(text="Сгенерировать промокод"), KeyboardButton(text="Таблица с пойзона")],
        [KeyboardButton(text="Сделать рассылку")],
        [KeyboardButton(text="Добавить / удалить админа")]
    ]
admin_keyboard = ReplyKeyboardMarkup(keyboard=admin_kb, resize_keyboard=True)

buy_sub_keyboard = InlineKeyboardBuilder()
buy_sub_keyboard.row(InlineKeyboardButton(text="🚀Купить подписку", callback_data="buy_sub"))

menu_button = InlineKeyboardButton(text="В меню", callback_data="start_menu")


def choice_generation_mode_keyboard(generations: int, delete_keyboard_message_id: int):
    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="👕Верх", callback_data=f"choice_generation_mode|upper|{generations}|{delete_keyboard_message_id}"))
    keyboard.add(InlineKeyboardButton(text="👖Низ", callback_data=f"choice_generation_mode|lower|{generations}|{delete_keyboard_message_id}"))
    keyboard.row(InlineKeyboardButton(text="🧥Полный образ(или платье)", callback_data=f"choice_generation_mode|full|{generations}|{delete_keyboard_message_id}"))
    keyboard.row(InlineKeyboardButton(text="Отмена", callback_data="cancel"))
    return keyboard

async def keyboard_for_pay(operation_id: str, url: str, time_limit: int, type_sub_id: int):
    pay_ai_keyboard = InlineKeyboardBuilder()
    pay_ai_keyboard.row(InlineKeyboardButton(text="Оплатить", web_app=WebAppInfo(url=url)))
    pay_ai_keyboard.row(InlineKeyboardButton(text="Оплата произведена",
                                             callback_data=f"is_paid|{operation_id}|{time_limit}|{type_sub_id}"))
    return pay_ai_keyboard


def subscriptions_keyboard(type_subs: list):
    keyboard = InlineKeyboardBuilder()
    for type_sub in type_subs:
        if type_sub.plan_name == "Free" or type_sub.from_promo:
            continue
        keyboard.row(InlineKeyboardButton(text=f"{type_sub.plan_name} - {type_sub.price} ₽/мес",
                                          callback_data=f"choice_sub|{type_sub.id}"))
    # keyboard.row(menu_button)
    return keyboard


def more_generations_keyboard(generations_packets: list):
    keyboard = InlineKeyboardBuilder()
    for generations_packet in generations_packets:
        keyboard.row(InlineKeyboardButton(text=f"{generations_packet.generations}"
                                               f" генераций - {generations_packet.price} ₽",
                                          callback_data=f"more_generations|{generations_packet.id}"))
    return  keyboard

def more_video_generations_keyboard(video_generations_packets: list):
    keyboard = InlineKeyboardBuilder()
    for generations_packet in video_generations_packets:
        keyboard.row(InlineKeyboardButton(text=f"{generations_packet.generations}"
                                               f" генераций - {generations_packet.price} ₽",
                                          callback_data=f"more_video_generations|{generations_packet.id}"))
    return  keyboard


menu_button = InlineKeyboardButton(text="В меню", callback_data="start_menu")
# buy_sub_keyboard = InlineKeyboardBuilder()
# buy_sub_keyboard.row(InlineKeyboardButton(text="Подписка", callback_data=f"subscribe"))
# buy_sub_keyboard.row(menu_button)


add_delete_admin = InlineKeyboardBuilder()
add_delete_admin.row(InlineKeyboardButton(text="Добавить админа", callback_data="add_admin"))
add_delete_admin.row(InlineKeyboardButton(text="Удалить админа", callback_data="delete_admin"))

# choice_bot_stat = InlineKeyboardBuilder()
#
# choice_bot_stat.row(InlineKeyboardButton(text="Количество новых пользователей", callback_data="statistic|new_users"))
# choice_bot_stat.row(InlineKeyboardButton(text="Количество всех запросов в GPT", callback_data="statistic|ai_requests"))
# choice_bot_stat.row(InlineKeyboardButton(text="Количество запросов с фото в GPT", callback_data="statistic|photo_ai_requests"))
# choice_bot_stat.row(InlineKeyboardButton(text="Количество операций по оплате", callback_data="statistic|operations"))
# choice_bot_stat.row(InlineKeyboardButton(text="Отмена", callback_data="cancel"))


type_users_mailing_keyboard = InlineKeyboardBuilder()
type_users_mailing_keyboard.row(InlineKeyboardButton(text='Всем пользователям', callback_data="type_users_mailing|all"))
type_users_mailing_keyboard.row(InlineKeyboardButton(text='С подпиской', callback_data="type_users_mailing|sub"))
type_users_mailing_keyboard.row(InlineKeyboardButton(text='Без подписки', callback_data="type_users_mailing|not_sub"))
type_users_mailing_keyboard.row(InlineKeyboardButton(text="Отмена", callback_data="cancel"))


db_tables_keyboard = InlineKeyboardBuilder()
row_to_kb = 1
for table_name in table_names:
    if row_to_kb == 1:
        db_tables_keyboard.row(InlineKeyboardButton(text=table_name, callback_data=f"db_tables|{table_name}"))
        row_to_kb = 2
    else:
        db_tables_keyboard.add(InlineKeyboardButton(text=table_name, callback_data=f"db_tables|{table_name}"))
        row_to_kb = 1
db_tables_keyboard.row(InlineKeyboardButton(text="Отмена", callback_data="cancel"))


statistics_keyboard = InlineKeyboardBuilder()
statistics_keyboard.row(InlineKeyboardButton(text="Grafana", web_app=WebAppInfo(url="https://grafana.astrabot.tech/d/ad7whs7/sozdavai-bot")))
statistics_keyboard.row(InlineKeyboardButton(text="Количество активных пользователей", callback_data="statistics|active_users"))
statistics_keyboard.row(InlineKeyboardButton(text="Количество новых пользователей", callback_data="statistics|users"))
statistics_keyboard.row(InlineKeyboardButton(text="Количество пользователей с активной подпиской", callback_data="statistics|active_subs"))
statistics_keyboard.row(InlineKeyboardButton(text="Количество запросов в GPT", callback_data="statistics|gpt"))


choice_bot_send = InlineKeyboardBuilder()
choice_bot_send.row(InlineKeyboardButton(text="Рассылка в боте", callback_data="mailing|all_bots"))
choice_bot_send.row(InlineKeyboardButton(text="Отмена", callback_data="cancel"))

cancel_keyboard = InlineKeyboardBuilder()
cancel_keyboard.row(InlineKeyboardButton(text="Отмена", callback_data="cancel"))

back_to_bots_keyboard = InlineKeyboardBuilder()
back_to_bots_keyboard.row(InlineKeyboardButton(text="Назад к выбору ботов", callback_data="back_to_bots"))

profiles_keyboard = InlineKeyboardBuilder()
profiles_keyboard.row(InlineKeyboardButton(text="Настройка контекста", callback_data="edit_user_context"))

confirm_clear_context = InlineKeyboardBuilder()
confirm_clear_context.row(InlineKeyboardButton(text="Очистить", callback_data="clear_context"))
confirm_clear_context.row(InlineKeyboardButton(text="Не очищать", callback_data="not_clear_context"))


settings_keyboard = InlineKeyboardBuilder()
settings_keyboard.row(InlineKeyboardButton(text="Универсальный", callback_data="mode|universal"))
settings_keyboard.row(InlineKeyboardButton(text="Специализированный", callback_data="mode|special"))

unlink_card_keyboard = InlineKeyboardBuilder()
unlink_card_keyboard.row(InlineKeyboardButton(text="Отвязать карту", callback_data="unlink_card"))
unlink_card_keyboard.row(InlineKeyboardButton(text="Отмена", callback_data="cancel"))

def delete_notification_keyboard(notif_id: int):
    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="❌Отменить напоминание", callback_data=f"delete_notification|{notif_id}"))
    return keyboard

def confirm_delete_notification_keyboard(notif_id: int):
    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="Да",
                                      callback_data=f"confirm_delete_notification|"
                                                    f"yes|{notif_id}"))
    keyboard.row(InlineKeyboardButton(text="Нет",
                                      callback_data=f"confirm_delete_notification|"
                                                    f"no|{notif_id}"))
    return keyboard


delete_payment_keyboard = InlineKeyboardBuilder()
delete_payment_keyboard.row(InlineKeyboardButton(text="Отвязать карту", callback_data="delete_payment"))


def confirm_send_mailing():
    keyboard = InlineKeyboardBuilder()
    keyboard.row(InlineKeyboardButton(text="Отравить", callback_data=f"confirm_send_mailing|yes"))
    keyboard.row(InlineKeyboardButton(text="Отменить", callback_data="confirm_send_mailing|no"))
    return keyboard


async def keyboard_for_pay_generations(operation_id: str, url: str, generations: int):
    pay_ai_keyboard = InlineKeyboardBuilder()
    pay_ai_keyboard.row(InlineKeyboardButton(text="Оплатить", web_app=WebAppInfo(url=url)))
    pay_ai_keyboard.row(InlineKeyboardButton(text="Оплата произведена",
                                             callback_data=f"generations_is_paid|{operation_id}|{generations}"))
    return pay_ai_keyboard

async def keyboard_for_pay_video_generations(operation_id: str, url: str, video_generations: int):
    pay_ai_keyboard = InlineKeyboardBuilder()
    pay_ai_keyboard.row(InlineKeyboardButton(text="Оплатить", web_app=WebAppInfo(url=url)))
    pay_ai_keyboard.row(InlineKeyboardButton(text="Оплата произведена",
                                             callback_data=f"video_generations_is_paid|{operation_id}|{video_generations}"))
    return pay_ai_keyboard


channel_sub_keyboard = InlineKeyboardBuilder()
channel_sub_keyboard.row(InlineKeyboardButton(text="⚡️Подписаться", url="https://t.me/sozdavai_media"))
