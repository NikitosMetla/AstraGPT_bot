import asyncio
import datetime

from aiogram import Router, F, Bot, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import any_state
from aiogram.types import Message, CallbackQuery

from data.keyboards import keyboard_for_pay, cancel_keyboard, buy_sub_keyboard, subscriptions_keyboard, \
    unlink_card_keyboard, keyboard_for_pay_generations
from db.repository import operation_repository, type_subscriptions_repository, generations_packets_repository
from db.repository import users_repository, subscriptions_repository
from settings import InputMessage, is_valid_email
from utils.payment_for_services import create_payment, check_payment, get_payment

payment_router = Router()



# @payment_router.callback_query(F.data == "unlink_card", any_state)
# async def sub_message(call: CallbackQuery, state: FSMContext, bot: Bot):
#     user_id = call.from_user.id
#     user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
#     type_sub = await type_subscriptions_repository.get_type_subscription_by_id(type_id=user_sub.type_subscription_id)
#     if user_sub is None or type_sub.plan_name == "Free":
#         await call.message.answer(
#             "✨Дорогой друг, на данный момент у тебя нет активной подписки и привязанной карты в частности")
#         return
#     if user_sub.method_id is None:
#         await call.message.answer(
#             "✨Дорогой друг, на данный момент у тебя уже не привязана никакая карта")
#         return
#     await subscriptions_repository.delete_payment_method(sub_id=user_sub.id)
#     await call.message.delete()
#     await call.message.answer("Отлично, отвязали твой метод оплаты. Теперь твоя подписка не сможет продлеваться автоматически")


@payment_router.callback_query(F.data.startswith("choice_sub|"), any_state)
async def get_day_statistic(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    print("\n\n\n\nsldfjkglskdjfgjksdfg\n\n\n\n")
    user = await users_repository.get_user_by_user_id(call.from_user.id)
    call_data = call.data.split("|")
    sub_type_id = int(call_data[1])
    sub_type = await type_subscriptions_repository.get_type_subscription_by_id(type_id=sub_type_id)
    price = sub_type.price
    max_generations = sub_type.max_generations
    if user.email is None:
        await state.set_state(InputMessage.enter_email)
        await state.update_data(max_generations=max_generations,
                                price=price, sub_type_id=sub_type_id)
        await call.message.answer("Для проведения оплаты нам понадобится адрес электронной почты,"
                                  " чтобы направить чек о покупке 🧾\n\nПожалуйста, введи свой email 🍏")
        try:
            await call.message.delete()
        finally:
            return
    payment = await create_payment(user.email, amount=price)
    await operation_repository.add_operation(operation_id=payment[0], user_id=call.from_user.id, is_paid=False,
                                                     url=payment[1], sub_type_id=sub_type_id)
    operation = await operation_repository.get_operation_by_operation_id(payment[0])
    keyboard = await keyboard_for_pay(operation_id=operation.id, url=payment[1], time_limit=30,
                                      type_sub_id=sub_type_id)
    await call.message.answer(text=f'Для дальнейше работы бота нужно приобрести подписку'
                                 f' за {price} рублей.\n\nПосле проведения платежа нажми на кнопку "Оплата произведена",'
                                 ' чтобы подтвердить платеж', reply_markup=keyboard.as_markup())
    try:
        await call.message.delete()
    finally:
        return


@payment_router.message(F.text, InputMessage.enter_email)
async def enter_user_email(message: types.Message, state: FSMContext, bot: Bot):
    if await is_valid_email(email=message.text):
        data = await state.update_data()
        price = data['price']
        max_generations = data['max_generations']
        type_sub_id = data.get("sub_type_id")
        await state.clear()
        await asyncio.sleep(1)
        await users_repository.update_email_by_user_id(user_id=message.from_user.id, email=message.text)
        delete_message = await message.answer("Отлично, мы сохранили твой email для следующих покупок")
        user = await users_repository.get_user_by_user_id(message.from_user.id)
        payment = await create_payment(user.email, amount=price)
        await operation_repository.add_operation(operation_id=payment[0], user_id=message.from_user.id, is_paid=False,
                                                 url=payment[1], sub_type_id=type_sub_id)
        operation = await operation_repository.get_operation_by_operation_id(payment[0])
        keyboard = await keyboard_for_pay(operation_id=operation.id, url=payment[1], time_limit=30,
                                          type_sub_id=type_sub_id)
        await message.answer(text=f'Для дальнейше работы ассистента нужно приобрести подписку'
                                       f' за {price} рублей.\n\nПосле проведения платежа нажми на кнопку "Оплата произведена",'
                                       ' чтобы подтвердить платеж', reply_markup=keyboard.as_markup())
        try:
            del_message_id = int(data.get("del_message_id"))
            await bot.delete_message(chat_id=message.from_user.id, message_id=del_message_id)
        except:
            return
        finally:
            await asyncio.sleep(2)
            try:
                await delete_message.delete()
            except:
                pass
    else:
        try:
            data = await state.update_data()
            del_message_id = int(data.get("del_message_id"))
            await bot.delete_message(chat_id=message.from_user.id, message_id=del_message_id)
        except:
            pass
        finally:
            del_message = await message.answer("Введеный тобой email некорректен, попробуй еще раз",
                                               reply_markup=cancel_keyboard.as_markup())
            await state.update_data(del_message_id=del_message.message_id)


@payment_router.callback_query(F.data.startswith("is_paid|"), any_state)
async def check_payment_callback(message: types.CallbackQuery, state: FSMContext, bot: Bot):
    data = message.data.split("|")
    operation_id = data[1]
    sub_type_id = int(data[3])
    user_id = message.from_user.id
    sub_type = await type_subscriptions_repository.get_type_subscription_by_id(type_id=sub_type_id)
    # user = await users_repository.get_user_by_user_id(message.from_user.id)
    operation = await operation_repository.get_operation_info_by_id(int(operation_id))
    payment_id = operation.operation_id
    payment = get_payment(payment_id)
    if await check_payment(payment_id):
        await operation_repository.update_paid_by_operation_id(payment_id)
        user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
        if user_sub is None:
            await subscriptions_repository.add_subscription(user_id=user_id,
                                                            time_limit_subscription=30,
                                                            active=True,
                                                            type_sub_id=sub_type_id,
                                                            method_id=payment.payment_method.id,
                                                            photo_generations=sub_type.max_generations)
        else:
            await subscriptions_repository.replace_subscription(subscription_id=user_sub.id,
                                                                user_id=user_id,
                                                                time_limit_subscription=30,
                                                                active=True,
                                                                type_sub_id=sub_type_id,
                                                                method_id=payment.payment_method.id,
                                                                photo_generations=sub_type.max_generations)
        await message.message.delete()
        await message.message.answer("Подписка успешно оформлена ✅")
    else:
        try:
            payment = await operation_repository.get_operation_by_operation_id(payment_id)
            keyboard = await keyboard_for_pay(operation_id=operation_id, url=payment.url, time_limit=30,
                                              type_sub_id=sub_type_id)
            await message.message.edit_text("Пока мы не видим, чтобы оплата была произведена( Подожди"
                                            " еще немного времени и убедись,"
                                            " что ты действительно произвел оплату. Если что-то пошло не так, свяжись"
                                            " с нами с помощью команды /support",
                                            reply_markup=keyboard.as_markup())
        finally:
            return


@payment_router.callback_query(F.data.startswith("more_generations|"))
async def buy_generations_callback(call: types.CallbackQuery):
    call_data = call.data.split("|")
    generations_packet_id = int(call_data[1])
    generations_packet = await generations_packets_repository.get_generations_packet_by_id(packet_id=generations_packet_id)
    generations = generations_packet.generations
    price = generations_packet.price
    user = await users_repository.get_user_by_user_id(user_id=call.from_user.id)
    payment = await create_payment(user.email, amount=price, description="Покупка дополнительных генераций фото")
    await operation_repository.add_operation(operation_id=payment[0], user_id=call.from_user.id, is_paid=False,
                                             url=payment[1])
    operation = await operation_repository.get_operation_by_operation_id(payment[0])
    keyboard = await keyboard_for_pay_generations(operation_id=operation.id, url=payment[1], generations=generations)
    await call.message.answer(text=f'✨Для дальнейшей работы бота нужно приобрести {generations} дополнительных генераций'
                                   f' за {price} рублей.\n\nПосле проведения платежа нажми на кнопку "Оплата произведена",'
                                   ' чтобы подтвердить платеж', reply_markup=keyboard.as_markup())
    try:
        await call.message.delete()
    finally:
        return


@payment_router.callback_query(F.data.startswith("generations_is_paid|"), any_state)
async def check_payment_callback(message: types.CallbackQuery, state: FSMContext, bot: Bot):
    operation_id = message.data.split("|")[1]
    operation = await operation_repository.get_operation_info_by_id(int(operation_id))
    payment_id = operation.operation_id
    generations = int(message.data.split("|")[2])
    if await check_payment(payment_id):
        await operation_repository.update_paid_by_operation_id(payment_id)
        payment = get_payment(payment_id)
        print(payment.payment_method.id)
        active_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=message.from_user.id)
        await subscriptions_repository.update_generations(subscription_id=active_sub.id, new_generations=generations)
        await message.message.delete()
        delete_message = await message.message.answer(f"{generations} генераций успешно приобретены ✅")
        await asyncio.sleep(5)
        await delete_message.delete()
    else:
        try:
            payment = await operation_repository.get_operation_by_operation_id(payment_id)
            keyboard = await keyboard_for_pay_generations(operation_id=operation.id, url=payment[1], generations=generations)
            await message.message.edit_text("❌Пока мы не видим, чтобы оплата была произведена( Погоди"
                                            " еще немного времени и убедись,"
                                            " что ты действительно произвел оплату. Если что-то пошло не так, свяжись"
                                            " с нами с помощью команды /support",
                                            reply_markup=keyboard.as_markup())
        finally:
            return