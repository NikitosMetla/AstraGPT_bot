from os import getenv

import aiohttp
import asyncio
import time
from typing import Optional, Dict, Any

from aiogram import Bot
from dotenv import load_dotenv, find_dotenv


class FitroomAPIError(Exception):
    """Base exception for Fitroom API errors."""
    pass


class TryonTaskFailed(FitroomAPIError):
    """Raised when a try-on task fails."""
    pass


load_dotenv(find_dotenv("../.env"))
fit_room_token = getenv("FITROOM_TOKEN")


class FitroomClient:
    BASE_URL = "https://platform.fitroom.app"

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self.api_key = fit_room_token
        self.session = session or aiohttp.ClientSession()

    async def _request(self, method: str, path: str, *, data=None, timeout=60) -> Dict[str, Any]:
        url = f"{self.BASE_URL}{path}"
        headers = {
            "X-API-KEY": self.api_key,
            "Origin": "https://platform.fitroom.app",  # Обязательный заголовок
            "Referer": "https://platform.fitroom.app/",  # Требуется для Cloudflare
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        backoff = 1.0
        max_retries = 5
        retry_count = 0

        while retry_count < max_retries:
            try:
                async with self.session.request(method, url, headers=headers, data=data, timeout=timeout) as resp:
                    text = await resp.text()

                    if resp.status == 402:
                        raise FitroomAPIError(
                            "Ошибка 402: недостаточно кредитов. "
                            "Пожалуйста, пополните баланс в личном кабинете."
                        )

                    if resp.status == 429:
                        print(f"Rate limit hit, waiting {backoff} seconds...")
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 30.0)
                        retry_count += 1
                        continue

                    if resp.status != 200:
                        raise FitroomAPIError(f"HTTP {resp.status}: {text}")

                    try:
                        return await resp.json()
                    except Exception as e:
                        raise FitroomAPIError(f"Failed to parse JSON response: {text}")

            except asyncio.TimeoutError:
                retry_count += 1
                if retry_count >= max_retries:
                    raise FitroomAPIError("Request timed out after multiple retries")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

        raise FitroomAPIError("Max retries exceeded")

    async def check_model_image(self, image_bytes: bytes) -> Dict[str, Any]:
        """
        Validates a model image for pose, lighting and returns allowed clothes types.
        """
        form = aiohttp.FormData()
        form.add_field("input_image", image_bytes, filename="model.jpg", content_type="image/jpeg")
        return await self._request("POST", "/api/tryon/input_check/v1/model", data=form)

    async def check_clothes_image(self, image_bytes: bytes) -> Dict[str, Any]:
        """
        Validates a clothing image and returns detected clothes_type.
        """
        form = aiohttp.FormData()
        form.add_field("input_image", image_bytes, filename="cloth.jpg", content_type="image/jpeg")
        return await self._request("POST", "/api/tryon/input_check/v1/clothes", data=form)

    async def check_account(self) -> Dict[str, Any]:
        """Проверка статуса аккаунта и баланса"""
        return await self._request("GET", "/api/account")

    async def create_tryon_task(
            self,
            model_bytes: bytes,
            cloth_bytes: bytes,
            cloth_type: str,
            lower_cloth_bytes: Optional[bytes] = None
    ) -> str:
        """
        Creates a try-on task. For combo try-on, set cloth_type="combo" and provide lower_cloth_bytes.
        Returns task_id.
        """
        form = aiohttp.FormData()
        if cloth_type is None:
            cloth_type = 'full'
        form.add_field(
            "model_image",
            model_bytes,
            filename="model.jpg",
            content_type='image/jpeg'  # Явное указание типа
        )

        if cloth_type == "combo":
            if not lower_cloth_bytes:
                raise ValueError("lower_cloth_bytes must be provided for combo try-on")
            form.add_field("cloth_image", cloth_bytes, filename="upper.jpg", content_type="image/jpeg")
            form.add_field("lower_cloth_image", lower_cloth_bytes, filename="lower.jpg", content_type="image/jpeg")
        else:
            form.add_field("cloth_image", cloth_bytes, filename="cloth.jpg", content_type="image/jpeg")

        form.add_field("cloth_type", cloth_type)

        print(f"Creating task with cloth_type: {cloth_type}")
        resp = await self._request("POST", "/api/tryon/v2/tasks", data=form)
        print(f"Task created successfully: {resp}")
        return resp["task_id"]

    async def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """
        Retrieves the status of a try-on task.
        """
        return await self._request("GET", f"/api/tryon/v2/tasks/{task_id}")

    async def download_result(self, download_url: str) -> bytes:
        """
        Downloads the resulting image bytes from the temporary signed URL.
        """
        async with self.session.get(download_url) as resp:
            if resp.status != 200:
                raise FitroomAPIError(f"Failed to download result: HTTP {resp.status}")
            return await resp.read()

    async def try_on(
            self,
            model_bytes: bytes,
            cloth_bytes: bytes,
            send_bot: Bot,
            chat_id: int,
            cloth_type: Optional[str] = "full",  # Теперь опциональный
            lower_cloth_bytes: Optional[bytes] = None,
            validate: bool = True,
            poll_interval: float = 3.0,  # Увеличил интервал
            timeout: float = 300.0
    ) -> bytes:
        """
        End-to-end try-on: optionally validates images, creates task, polls status,
        and returns final image bytes.
        """
        if validate:
            # Проверяем модель
            model_check = await self.check_model_image(model_bytes)
            print(f"Model check result: {model_check}")

            if not model_check.get("is_good", False):
                raise FitroomAPIError(f"Model image invalid: {model_check}")

            # Проверяем одежду
            clothes_check = await self.check_clothes_image(cloth_bytes)
            print(f"Clothes check result: {clothes_check}")

            if not clothes_check.get("is_clothes", False):
                raise FitroomAPIError(f"Clothes image invalid: {clothes_check}")

            # ВАЖНО: используем тип одежды, определенный API, если не указан явно
            if cloth_type is None:
                cloth_type = clothes_check["clothes_type"]
                print(f"Auto-detected cloth_type: {cloth_type}")
            else:
                # Если тип указан принудительно, проверяем совместимость
                detected_type = clothes_check["clothes_type"]
                if cloth_type != detected_type:
                    print(
                        f"❌ КРИТИЧЕСКАЯ ОШИБКА: Указанный cloth_type='{cloth_type}' не совпадает с определенным API='{detected_type}'")
                    print(f"   Это может привести к зависанию задачи в статусе CREATED!")
                    print(f"   Рекомендуется использовать cloth_type='{detected_type}'")

                    # Автоматически исправляем
                    print(f"   Автоматически исправляю на '{detected_type}'")
                    cloth_type = detected_type

            # Проверяем совместимость с моделью
            good_clothes_types = model_check.get("good_clothes_types", [])
            if cloth_type not in good_clothes_types:
                print(f"Warning: cloth_type '{cloth_type}' not in good_clothes_types {good_clothes_types}")

        # Создаем задачу
        task_id = await self.create_tryon_task(model_bytes, cloth_bytes, cloth_type, lower_cloth_bytes)
        # print(f"Task created with ID: {task_id}")

        # Ожидаем выполнения с более частым логированием
        start = time.time()
        poll_count = 0

        # Отправляем начальное сообщение и сохраняем его для редактирования
        edit_message = await send_bot.send_message(
            chat_id,
            "⏳ Обработка: 0%\n[░░░░░░░░░░]"
        )

        while True:
            # Получаем статус задачи и прогресс
            status = await self.get_task_status(task_id)
            poll_count += 1
            current_status = status.get("status", "UNKNOWN")
            progress = status.get("progress", 0)

            print(f"Poll #{poll_count}: Status={current_status}, Progress={progress}%")

            # Формируем текст с прогресс-баром
            bar_length = 10
            filled = int(bar_length * progress / 100)
            bar = '█' * filled + '░' * (bar_length - filled)
            text = (
                f"⏳ Обработка: {progress}%\n"
                f"[{bar}]\n"
                f"Статус: {'<b>В процессе</b>' if current_status == 'PROCESSING' else '<b>Принято в обработку</b>' if current_status == 'CREATED' else '<b>ГОТОВО!</b>'}"
            )

            try:
                # Редактируем ранее отправленное сообщение
                await send_bot.edit_message_text(
                    text=text,
                    chat_id=edit_message.chat.id,
                    message_id=edit_message.message_id
                )
            except Exception as e:
                # Логируем ошибки редактирования, но продолжаем попытки
                print(f"Ошибка редактирования сообщения: {e}")

            if current_status == "COMPLETED":
                await send_bot.delete_message(chat_id=chat_id,
                                              message_id=edit_message.message_id)
                download_url = status.get("download_signed_url")
                if not download_url:
                    raise FitroomAPIError("No download URL in completed task")
                print(f"Task completed! Downloading from: {download_url[:50]}...")
                return await self.download_result(download_url)

            if current_status == "FAILED":
                await send_bot.delete_message(chat_id=chat_id,
                                              message_id=edit_message.message_id)
                error_msg = status.get("error", "Unknown error")
                raise TryonTaskFailed(f"Task {task_id} failed: {error_msg}")
            # Проверяем таймаут
            elapsed = time.time() - start
            if elapsed > timeout:
                raise FitroomAPIError(
                    f"Try-on task timed out after {elapsed:.1f} seconds. Last status: {current_status}")

            # Особая логика для CREATED статуса
            if current_status == "CREATED" and poll_count > 10:
                print(f"Warning: Task stuck in CREATED status for {poll_count} polls ({elapsed:.1f}s)")

                # После 30 секунд в CREATED статусе - это аномалия
                if elapsed > 30:
                    print("Task appears to be stuck. This might indicate a service issue.")
                    # Можно попробовать создать новую задачу или обратиться в поддержку

            await asyncio.sleep(poll_interval)

    async def close(self):
        """Closes underlying HTTP session."""
        await self.session.close()