from fastapi import FastAPI, Request, HTTPException
import uvicorn
import json

# Импорты из твоего проекта (добавь нужные пути)
from db.repository import operation_repository, type_subscriptions_repository
from db.repository import users_repository, subscriptions_repository
from settings import get_current_bot
from utils.payment_for_services import get_payment

app = FastAPI()

from settings import logger


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


@app.post("/yookassa/webhook")
async def yookassa_webhook(request: Request):
    """
    Эндпоинт для автоматической обработки уведомлений от ЮKassa
    """
    try:
        # Получаем данные от ЮKassa
        raw_body = await request.body()
        event_data = json.loads(raw_body.decode('utf-8'))

        logger.info(f"YooKassa webhook received: {event_data}")

        event_type = event_data.get('event')
        payment_object = event_data.get('object', {})
        payment_id = payment_object.get('id')

        # Обрабатываем только успешные платежи
        if event_type == "payment.succeeded":
            await handle_successful_payment(payment_id)

        return {"status": "ok"}

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        print(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def handle_successful_payment(payment_id: str):
    """
    Обработка успешного платежа - делает то же, что и твоя кнопка "Оплата произведена"
    """
    try:
        print(f"Processing successful payment: {payment_id}")

        # Получаем операцию из твоей БД
        operation = await operation_repository.get_operation_by_operation_id(payment_id)
        if not operation:
            print(f"Operation not found for payment_id: {payment_id}")
            return

        user_id = operation.user_id

        # Получаем данные о платеже из ЮKassa
        payment = get_payment(payment_id)

        # Помечаем операцию как оплаченную
        await operation_repository.update_paid_by_operation_id(payment_id)

        # Определяем тип подписки из метаданных или другим способом
        # Здесь нужно будет добавить логику получения sub_type_id
        # Возможно, сохранять в operation или в metadata платежа


        if operation.type_operation == "sub_operation":
            sub_type_id = operation.sub_type_id
            if sub_type_id is None:
                logger.log()
            sub_type = await type_subscriptions_repository.get_type_subscription_by_id(type_id=sub_type_id)
        # Проверяем активную подписку пользователя
            user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)

            if user_sub is None:
            #     # Создаем новую подписку
                await subscriptions_repository.add_subscription(
                    user_id=user_id,
                    time_limit_subscription=30,
                    active=True,
                    type_sub_id=sub_type_id,
                    method_id=payment.payment_method.id,
                    photo_generations=sub_type.max_generations
                )
            else:
                # Заменяем существующую подписку
                await subscriptions_repository.replace_subscription(
                    subscription_id=user_sub.id,
                    user_id=user_id,
                    time_limit_subscription=30,
                    active=True,
                    type_sub_id=sub_type_id,
                    method_id=payment.payment_method.id,
                    photo_generations=sub_type.max_generations
                )

            logger.log(f"✅Subscription activated for payment: {payment_id}")
            # Здесь можно добавить отправку уведомления в Telegram бот
            await send_telegram_notification(user_id, "Подписка успешно оформлена ✅")
        elif operation.type_operation == "generations_operation":
            pass

    except Exception as e:
        print(f"Error handling successful payment {payment_id}: {e}")
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
        pass
    except Exception as e:
        print(f"Error sending telegram notification: {e}")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        reload=False
    )