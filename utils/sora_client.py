"""
Асинхронный клиент для Sora 2 API на kie.ai
Production-ready код с полной обработкой ошибок и retry логикой
"""

import asyncio
import base64
import json
import os
from typing import Optional, Union
from pathlib import Path
import aiohttp
from dotenv import load_dotenv, find_dotenv

from settings import logger


load_dotenv(find_dotenv())
KIE_API_KEY = os.getenv("KIE_API_KEY")


class KieSora2Error(Exception):
    """Базовое исключение для ошибок API"""
    pass


class InsufficientCreditsError(KieSora2Error):
    """Недостаточно кредитов"""
    pass


class RateLimitError(KieSora2Error):
    """Превышен лимит запросов"""
    pass


class ContentPolicyError(KieSora2Error):
    """Нарушение content policy"""
    pass


class KieSora2Client:
    """Асинхронный клиент для работы с Sora 2 API"""

    BASE_URL = "https://api.kie.ai/api/v1"

    def __init__(
            self,
            api_key: str | None = KIE_API_KEY,
            max_retries: int = 3,
            timeout: int = 60,
            poll_interval: int = 10,
            max_poll_time: int = 900
    ):
        self.api_key = api_key
        self.max_retries = max_retries
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.poll_interval = poll_interval
        self.max_poll_time = max_poll_time
        self.session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()  # Добавь это

    async def _ensure_session(self):
        """Проверка и создание сессии при необходимости"""
        async with self._session_lock:
            if self.session is None or self.session.closed:
                logger.info("Создание новой HTTP сессии")
                self.session = aiohttp.ClientSession(
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    timeout=self.timeout
                )

    async def close(self):
        """Закрытие сессии"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("HTTP сессия закрыта")

    async def __aenter__(self):
        """Context manager - создание сессии"""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager - закрытие сессии"""
        await self.close()

    def _handle_error(self, status: int, response_data: dict) -> None:
        """Обработка ошибок API"""
        error_msg = response_data.get("msg", "Unknown error")

        error_mapping = {
            401: KieSora2Error(f"Неверный API ключ: {error_msg}"),
            402: InsufficientCreditsError(f"Недостаточно кредитов: {error_msg}"),
            404: KieSora2Error(f"Эндпоинт не найден: {error_msg}"),
            422: KieSora2Error(f"Ошибка валидации: {error_msg}"),
            429: RateLimitError(f"Превышен лимит запросов: {error_msg}"),
            455: KieSora2Error(f"Сервис недоступен (maintenance): {error_msg}"),
            500: KieSora2Error(f"Ошибка сервера: {error_msg}"),
            501: KieSora2Error(f"Ошибка генерации: {error_msg}"),
            505: KieSora2Error(f"Функция отключена: {error_msg}")
        }

        # Проверка на content policy ошибки
        if "public_error" in error_msg or "policy" in error_msg.lower():
            raise ContentPolicyError(f"Нарушение content policy: {error_msg}")

        raise error_mapping.get(status, KieSora2Error(f"HTTP {status}: {error_msg}"))

    async def _request_with_retry(
            self,
            method: str,
            url: str,
            **kwargs
    ) -> dict:
        """Выполнение запроса с retry логикой"""
        for attempt in range(self.max_retries):
            try:
                # Проверяем сессию перед каждым запросом
                await self._ensure_session()

                async with self.session.request(method, url, **kwargs) as response:
                    data = await response.json()

                    # Успешный запрос
                    if response.status == 200:
                        return data

                    # Rate limit - exponential backoff
                    if response.status == 429:
                        wait_time = 2 ** attempt * 5
                        logger.warning(f"Rate limit, ожидание {wait_time}с (попытка {attempt + 1}/{self.max_retries})")
                        await asyncio.sleep(wait_time)
                        continue

                    # Остальные ошибки
                    self._handle_error(response.status, data)

            except asyncio.TimeoutError:
                if attempt == self.max_retries - 1:
                    raise KieSora2Error("Превышен таймаут запроса")
                logger.warning(f"Таймаут, повтор попытки {attempt + 1}/{self.max_retries}")
                await asyncio.sleep(5)

            except aiohttp.ClientError as e:
                if attempt == self.max_retries - 1:
                    raise KieSora2Error(f"Ошибка соединения: {e}")

                # При ошибке соединения - пересоздаем сессию
                logger.warning(
                    f"Ошибка соединения: {e}, пересоздание сессии (попытка {attempt + 1}/{self.max_retries})")
                await self.close()
                await asyncio.sleep(2 ** attempt)
                continue

            except (InsufficientCreditsError, ContentPolicyError):
                raise  # Не ретраим эти ошибки

            except KieSora2Error:
                if attempt == self.max_retries - 1:
                    raise
                logger.warning(f"Повтор попытки {attempt + 1}/{self.max_retries}")
                await asyncio.sleep(2 ** attempt)

        raise KieSora2Error("Превышено максимальное количество попыток")

    async def _create_task(self, endpoint: str, payload: dict) -> str:
        """Создание задачи генерации"""
        url = f"{self.BASE_URL}/{endpoint}"
        logger.info(f"Создание задачи: {endpoint}")

        data = await self._request_with_retry("POST", url, json=payload)

        if data.get("code") != 200:
            raise KieSora2Error(f"Ошибка создания задачи: {data.get('msg')}")

        task_id = data["data"]["taskId"]
        logger.info(f"Задача создана: {task_id}")
        return task_id

    async def _poll_task_status(self, task_id: str) -> str | list[str]:
        """Polling статуса задачи до завершения"""
        url = f"{self.BASE_URL}/jobs/recordInfo"
        start_time = asyncio.get_event_loop().time()

        IN_PROGRESS = {"waiting", "wait", "queue", "queueing", "processing", "generating", "pending"}
        DONE_OK = {"success"}
        DONE_FAIL = {"fail", "failed", "error", "timeout", "canceled"}

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > self.max_poll_time:
                raise KieSora2Error(f"Таймаут ожидания генерации ({self.max_poll_time}с)")

            data = await self._request_with_retry("GET", url, params={"taskId": task_id})
            if data.get("code") != 200:
                raise KieSora2Error(f"Ошибка проверки статуса: {data.get('msg')}")

            task_data = data["data"]
            raw_state = (task_data.get("state") or "").strip()
            state = raw_state.lower()

            if state in IN_PROGRESS:
                logger.info(f"Генерация в процессе... ({int(elapsed)}с) state={raw_state}")
                await asyncio.sleep(self.poll_interval)
                continue

            if state in DONE_OK:
                result_json = task_data.get("resultJson")
                if not result_json:
                    raise KieSora2Error("Видео сгенерировано, но результат отсутствует")

                try:
                    result_data = json.loads(result_json) if isinstance(result_json, str) else result_json
                except Exception as e:
                    raise KieSora2Error(f"Не удалось распарсить resultJson: {e}")

                result_urls = result_data.get("resultUrls") or result_data.get("result_urls") or []
                if not isinstance(result_urls, list) or not result_urls:
                    raise KieSora2Error("Видео сгенерировано, но URL отсутствует")

                logger.info(f"Генерация завершена за {int(elapsed)}с")
                return [result_urls[0]]

            if state in DONE_FAIL:
                error_code = task_data.get("failCode", "Unknown")
                error_msg = task_data.get("failMsg", "Неизвестная ошибка")
                raise KieSora2Error(f"Ошибка генерации [{error_code}]: {error_msg}")

            # неизвестное состояние — трактуем как промежуточное, но предупредим
            logger.warning(f"Неизвестный статус от API: {raw_state} — считаю как IN_PROGRESS")
            await asyncio.sleep(self.poll_interval)

    async def text_to_video(
            self,
            prompt: str,
            aspect_ratio: str = "landscape",  # Было "landscape"
            quality: str = "hd",
            callback_url: Optional[str] = None,
            enable_fallback: bool = True
    ) -> str:
        """
        Генерация видео из текста

        Args:
            prompt: Текстовое описание желаемого видео
            aspect_ratio: Соотношение сторон (например: "landscape", "portrait", "1:1")
            quality: Качество видео ("hd" или другие поддерживаемые значения)
            callback_url: URL для webhook callback (опционально)
            enable_fallback: Включить fallback при content policy ошибках

        Returns:
            str: URL сгенерированного видео

        Raises:
            KieSora2Error: При ошибке генерации
            InsufficientCreditsError: При недостатке кредитов
            ContentPolicyError: При нарушении content policy
        """
        # if not self.session:
        #     raise KieSora2Error("Используйте 'async with KieSora2Client(...)' для создания сессии")

        payload = {
            "model": "sora-2-text-to-video",
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,  # НЕ aspectRatio!
                "quality": quality
            }
        }
        # enableFallback НЕ поддерживается в новом API

        if callback_url:
            payload["callBackUrl"] = callback_url  # На верхнем уровне, НЕ в input

        task_id = await self._create_task("jobs/createTask", payload)

        # Если передан callback_url, возвращаем task_id без ожидания
        if callback_url:
            logger.info(f"Callback URL указан, возвращаем task_id: {task_id}")
            return task_id

        # Иначе ждём завершения
        return await self._poll_task_status(task_id)

    async def image_to_video(
            self,
            image: Union[str, bytes, Path],
            prompt: str,
            aspect_ratio: str = "landscape",
            quality: str = "standard",  # Изменено на standard по умолчанию
            callback_url: Optional[str] = None,
            enable_fallback: bool = True
    ) -> str:
        # Обработка разных форматов входного изображения
        image_data = None

        if isinstance(image, bytes):
            # Конвертируем байты в base64 с правильным форматом data URL
            image_data = f"data:image/png;base64,{base64.b64encode(image).decode('utf-8')}"
            logger.info(f"Изображение конвертировано в data URL (размер: {len(image)} байт)")

        elif isinstance(image, str):
            # URL или путь к файлу
            if image.startswith(("http://", "https://")):
                image_data = image
                logger.info(f"Используется URL изображения: {image}")
            elif image.startswith("data:image"):
                # Уже data URL
                image_data = image
                logger.info("Используется data URL")
            else:
                image_path = Path(image)
                if not image_path.exists():
                    raise KieSora2Error(f"Файл не найден: {image}")
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
                image_data = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('utf-8')}"
                logger.info(f"Изображение загружено из файла и конвертировано в data URL: {image}")

        elif isinstance(image, Path):
            if not image.exists():
                raise KieSora2Error(f"Файл не найден: {image}")
            with open(image, "rb") as f:
                image_bytes = f.read()
            image_data = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('utf-8')}"
            logger.info(f"Изображение загружено из Path и конвертировано в data URL: {image}")

        else:
            raise KieSora2Error("image должен быть URL (str), путём к файлу (str/Path) или bytes")

        payload = {
            "model": "sora-2-image-to-video",
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                # "quality": quality,
                "image_urls": [image_data]  # Поле image_url согласно документации
            }
        }

        if callback_url:
            payload["callBackUrl"] = callback_url

        # Добавим детальное логирование для отладки
        logger.info(f"Отправка запроса с payload структурой:")
        logger.info(f"  model: {payload['model']}")
        logger.info(f"  input.prompt: {prompt[:50]}...")
        logger.info(f"  input.aspect_ratio: {aspect_ratio}")
        logger.info(f"  input.quality: {quality}")
        logger.info(f"  input.image_url присутствует: {'Да' if image_data else 'Нет'}")
        logger.info(f"  input.image_url тип: {'data URL' if image_data and image_data.startswith('data:') else 'HTTP URL' if image_data else 'Отсутствует'}")

        task_id = await self._create_task("jobs/createTask", payload)

        if callback_url:
            logger.info(f"Callback URL указан, возвращаем task_id: {task_id}")
            return task_id

        return await self._poll_task_status(task_id)

    async def get_task_status(self, task_id: str) -> dict:
        """
        Получить статус задачи

        Args:
            task_id: ID задачи

        Returns:
            dict: Информация о статусе задачи
        """
        url = f"{self.BASE_URL}/jobs/recordInfo"
        data = await self._request_with_retry("GET", url, params={"taskId": task_id})

        if data.get("code") != 200:
            raise KieSora2Error(f"Ошибка получения статуса: {data.get('msg')}")

        return data["data"]

    async def get_credits_balance(self) -> float:
        """
        Получить баланс кредитов

        Returns:
            float: Количество доступных кредитов
        """
        url = f"{self.BASE_URL}/chat/credit"
        data = await self._request_with_retry("GET", url)

        if data.get("code") != 200:
            raise KieSora2Error(f"Ошибка получения баланса: {data.get('msg')}")

        return float(data["data"].get("credits", 0))


# ============================================
# ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ
# ============================================

async def example_text_to_video():
    """Пример генерации видео из текста"""
    async with KieSora2Client(api_key=KIE_API_KEY) as client:
        try:
            # Проверяем баланс
            # balance = await client.get_credits_balance()
            # logger.info(f"Баланс кредитов: {balance}")
            logger.info(f"Start task")

            # Генерируем видео
            video_url = await client.text_to_video(
                prompt="Short vido where cat playing piano in a concert hall, cinematic lighting",
                aspect_ratio="landscape",
                quality="hd"
            )

            logger.info(f"Видео готово: {video_url}")
            return video_url

        except InsufficientCreditsError as e:
            logger.error(f"Недостаточно средств: {e}")
        except ContentPolicyError as e:
            logger.error(f"Нарушение политики: {e}")
        except KieSora2Error as e:
            logger.error(f"Ошибка API: {e}")


async def example_image_to_video():
    """Пример генерации видео из изображения"""
    async with KieSora2Client(api_key=KIE_API_KEY) as client:
        try:
            # Вариант 1: Из URL
            video_url = await client.image_to_video(
                image="https://example.com/image.jpg",
                prompt="Make the person smile and wave",
                aspect_ratio="landscape"
            )

            # Вариант 2: Из локального файла
            # video_url = await client.image_to_video(
            #     image="path/to/image.jpg",
            #     prompt="Add motion and life to the scene"
            # )

            # Вариант 3: Из bytes
            # with open("image.jpg", "rb") as f:
            #     image_bytes = f.read()
            # video_url = await client.image_to_video(
            #     image=image_bytes,
            #     prompt="Animate the scene"
            # )

            logger.info(f"Видео готово: {video_url}")
            return video_url

        except KieSora2Error as e:
            logger.error(f"Ошибка: {e}")


async def example_with_webhook():
    """Пример использования с webhook callback"""
    async with KieSora2Client(api_key=KIE_API_KEY) as client:
        try:
            # Запускаем генерацию с callback
            task_id = await client.text_to_video(
                prompt="Beautiful sunset over mountains",
                callback_url="https://your-server.com/webhook"
            )

            logger.info(f"Задача создана: {task_id}")
            logger.info("Результат придёт на webhook")

            # Можно проверить статус вручную позже
            await asyncio.sleep(60)  # Ждём минуту
            status = await client.get_task_status(task_id)
            logger.info(f"Статус: {status}")

        except KieSora2Error as e:
            logger.error(f"Ошибка: {e}")


async def example_multiple_videos():
    """Пример генерации нескольких видео параллельно"""
    prompts = [
        "A dog running on the beach",
        "City lights at night, timelapse",
        "Waterfall in a forest, peaceful"
    ]

    async with KieSora2Client(api_key=KIE_API_KEY) as client:
        try:
            # Запускаем все генерации параллельно
            tasks = [
                client.text_to_video(prompt=p, aspect_ratio="landscape")
                for p in prompts
            ]

            # Ждём завершения всех
            videos = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(videos):
                if isinstance(result, Exception):
                    logger.error(f"Видео {i + 1} ошибка: {result}")
                else:
                    logger.info(f"Видео {i + 1} готово: {result}")

            return videos

        except Exception as e:
            logger.error(f"Общая ошибка: {e}")


# Запуск примеров
# if __name__ == "__main__":
#     # Раскомментируйте нужный пример:
#
#     print(asyncio.run(example_text_to_video()))
#     # asyncio.run(example_image_to_video())
#     # asyncio.run(example_with_webhook())
#     # asyncio.run(example_multiple_videos())
#
#     pass