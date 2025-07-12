import os
import asyncio
import aiohttp
import time
from typing import Tuple

API_BASE = "https://thenewblack.ai/api/1.1/wf"
EMAIL = os.getenv("TNB_EMAIL")  # Ваш e-mail, задайте через переменные окружения
PASSWORD = os.getenv("TNB_PASSWORD")  # Ваш пароль, задайте через переменные окружения


async def submit_vto_request(
        session: aiohttp.ClientSession,
        model_bytes: bytes,
        clothing_bytes: bytes,
        clothing_type: str
) -> str:
    """
    Шаг 1: Отправка первого запроса для получения ID задачи.
    Возвращает строковый ID, который нужно использовать через 30–40 секунд.
    """
    data = {
        'email': EMAIL,
        'password': PASSWORD,
        'clothing_type': clothing_type
    }
    files = {
        'model_photo': ('model.jpg', model_bytes, 'image/jpeg'),
        'clothing_photo': ('clothing.jpg', clothing_bytes, 'image/jpeg'),
    }
    async with session.post(f"{API_BASE}/vto", data=data, files=files) as resp:
        resp.raise_for_status()
        task_id = await resp.text()
        return task_id.strip()


async def retrieve_result(
        session: aiohttp.ClientSession,
        task_id: str
) -> bytes:
    """
    Шаг 2: Через 30–40 секунд запрашиваем готовый результат по полученному ID.
    Получаем URL итогового изображения, скачиваем и возвращаем его байты.
    """
    data = {
        'email': EMAIL,
        'password': PASSWORD,
        'id': task_id
    }
    # Делаем паузу в 35 секунд для асинхронной генерации
    await asyncio.sleep(35)
    async with session.post(f"{API_BASE}/results", data=data) as resp:
        resp.raise_for_status()
        result_url = (await resp.text()).strip()

    # Скачиваем итоговое изображение
    async with session.get(result_url) as img_resp:
        img_resp.raise_for_status()
        return await img_resp.read()


async def virtual_try_on(
        model_bytes: bytes,
        clothing_bytes: bytes,
        clothing_type: str = "tops"
) -> bytes:
    """
    Основная функция для виртуальной примерки.
    Возвращает байты изображения с одетым на модель предметом одежды.
    """
    if clothing_type not in {"tops", "bottoms", "one-pieces"}:
        raise ValueError("Неверный тип одежды: допустимо только 'tops', 'bottoms' или 'one-pieces'")

    async with aiohttp.ClientSession() as session:
        task_id = await submit_vto_request(session, model_bytes, clothing_bytes, clothing_type)
        result_bytes = await retrieve_result(session, task_id)
        return result_bytes