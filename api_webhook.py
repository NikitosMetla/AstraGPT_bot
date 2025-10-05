import asyncio
import pprint
import traceback
from typing import Dict, Any

from fastapi import FastAPI, Request, HTTPException
import uvicorn
import json

from pydantic import BaseModel

# Импорты из твоего проекта (добавь нужные пути)
from db.repository import operation_repository, type_subscriptions_repository, generations_packets_repository
from db.repository import users_repository, subscriptions_repository
from settings import get_current_bot, initialize_logger, set_current_loop
from utils.payment_for_services import get_payment, check_payment

from contextlib import asynccontextmanager


# ✅ ДОБАВИТЬ ЭТУ ФУНКЦИЮ:
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Инициализация при запуске и очистка при остановке приложения
    """
    # Startup
    try:
        # Получаем текущий event loop, который создал uvicorn
        loop = asyncio.get_running_loop()

        # Устанавливаем его для logger
        set_current_loop(loop)

        # Инициализируем logger
        initialize_logger()

        logger.log("START_BOT", "🚀 YooKassa Webhook FastAPI started")

    except Exception as e:
        print(f"Error during startup: {traceback.format_exc()}")

    yield  # Приложение работает

    # Shutdown (опционально)
    logger.info("Shutting down YooKassa webhook server")

app = FastAPI(lifespan=lifespan)

from settings import logger

# initialize_logger()
#
# try:
#     loop = asyncio.get_event_loop()
# except RuntimeError:
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#
# set_current_loop(loop)

class YooKassaWebhookData(BaseModel):
    type: str
    event: str
    object: Dict[str, Any]


@app.get("/")
async def root():
    return {"message": "FastAPI server is running"}


@app.get("/webhook")
async def webhook_get():
    return {"status": "ok", "method": "GET"}


@app.post("/webhook")
async def webhook_post(request: Request):
    try:
        payload = await request.json()
        print("Received webhook payload:", payload)
        return {"status": "ok", "received": payload}
    except Exception as e:
        try:
            text = await request.body()
            print("Received raw data:", text.decode("utf-8"))
            return {"status": "ok", "received_raw": text.decode("utf-8")}
        except Exception as decode_error:
            print(f"Error processing request: {decode_error}")
            raise HTTPException(status_code=400, detail="Invalid request format")
#

@app.post("/yookassa/webhook")
async def yookassa_webhook(data: YooKassaWebhookData):
    """
    Эндпоинт для автоматической обработки уведомлений от ЮKassa
    """
    try:
        event_data = data.model_dump()

        logger.info(f"YooKassa webhook received: {event_data}")

        event_type = event_data.get('event')
        payment_object = event_data.get('object', {})
        payment_id = payment_object.get('id')
        logger.info(f"event_data: {event_data}")
        try:
            pprint.pprint(event_data)
        except:
            pass
        # Обрабатываем только успешные платежи
        if event_type == "payment.succeeded":
            await handle_successful_payment(payment_id)

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error processing webhook: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def handle_successful_payment(payment_id: str):
    """
    Обработка успешного платежа - делает то же, что и твоя кнопка "Оплата произведена"
    """
    try:

        # Получаем операцию из твоей БД
        operation = await operation_repository.get_operation_by_operation_id(payment_id)
        if not operation:
            logger.log("YooKassaError",f"Operation not found for payment_id: {payment_id}")
            return

        if operation.is_paid:
            logger.log("YooKassaError", f"Operation is paid already.  payment_id: {payment_id}")
            return

        is_paid = await check_payment(payment_id=operation.operation_id)
        if not is_paid:
            logger.log("YooKassaError", f"The operation wasn't paid "
                                        f"for but ended up in the webhook.  payment_id: {payment_id}")
            return
        user_id = operation.user_id

        payment = get_payment(payment_id)

        await operation_repository.update_paid_by_operation_id(payment_id)

        user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
        if operation.type_operation == "sub_operation":
            sub_type_id = operation.sub_type_id
            sub_type = await type_subscriptions_repository.get_type_subscription_by_id(type_id=sub_type_id)
            if sub_type_id is None:
                logger.log("YooKassaError", f"No sub_type_id for operations <b>{operation.id}</b>")


            if user_sub is None or (sub_type and sub_type.plan_name == "Free"):
                await subscriptions_repository.add_subscription(
                    user_id=user_id,
                    time_limit_subscription=30,
                    active=True,
                    type_sub_id=sub_type_id,
                    method_id=payment.payment_method.id if payment.payment_method else None,
                    photo_generations=sub_type.max_generations
                )
            else:
                await subscriptions_repository.replace_subscription(
                    subscription_id=user_sub.id,
                    user_id=user_id,
                    time_limit_subscription=30,
                    active=True,
                    type_sub_id=sub_type_id,
                    method_id=payment.payment_method.id if payment.payment_method else None,
                    photo_generations=sub_type.max_generations
                )

            logger.log("YooKassaPAYMENT_SUCCES", f"✅Subscription activated for payment: {payment_id}")
            await send_telegram_notification(user_id, "Подписка успешно оформлена ✅")


        elif operation.type_operation == "generations_operation":
            generations_pack_id = operation.generations_pack_id
            if generations_pack_id is None:
                logger.log("YooKassaError", f"No generations_pack_id for operations <b>{operation.id}</b>")
            generations_pack = await generations_packets_repository.get_generations_packet_by_id(packet_id=generations_pack_id)
            await subscriptions_repository.update_generations(subscription_id=user_sub.id,
                                                              new_generations=generations_pack.generations)
            logger.log("YooKassaPAYMENT_SUCCES", f"✅generations added to sub for payment: {payment_id}")
            await send_telegram_notification(user_id, f"{generations_pack.generations} генераций успешно приобретены ✅")
        payment_message_id = operation.payment_message_id
        if payment_message_id is not None:
            try:
                from bot import main_bot
                await main_bot.delete_message(chat_id=user_id, message_id=payment_message_id)
            except:
                try:
                    from test_bot import test_bot
                    await test_bot.delete_message(chat_id=user_id, message_id=payment_message_id)
                except:
                    logger.log("YooKassaError", traceback.format_exc())


    except Exception as e:
        logger.log("YooKassaError", f"Error handling successful payment {payment_id}: {traceback.format_exc()}")
        # Можно добавить логирование в файл или отправку в мониторинг


# Функция для отправки уведомлений в Telegram (опционально)
async def send_telegram_notification(user_id: int, message: str):
    """
    Отправляет уведомление пользователю в Telegram
    """
    try:
        from bot import main_bot
        bot = main_bot
        await bot.send_message(chat_id=user_id, text=message)
        try:
            from test_bot import test_bot
            await test_bot.send_message(chat_id=user_id, text=message)
        except:
            pass
    except Exception as e:
        logger.log("YooKassaError",f"Error sending telegram notification: {traceback.format_exc()}")


if __name__ == "__main__":
    # logger.log("START_BOT", f"🚀YouKassaWebhook was STARTED")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        reload=False
    )