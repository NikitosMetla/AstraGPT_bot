from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import pprint
import traceback
from collections import defaultdict
from typing import Any, Awaitable, Callable, Optional, Sequence, Literal
from typing import Dict

import aiohttp
from dotenv import find_dotenv, load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError, BadRequestError, )

from data.keyboards import subscriptions_keyboard
from settings import get_current_datetime_string, print_log
from utils import web_search_agent
from utils.create_notification import schedule_notification, NotificationSchedulerError
from utils.parse_gpt_text import sanitize_with_links
from utils.runway_api import generate_image_bytes

# combined_gpt_tools.py

_thread_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class NoSubscription(Exception):
    """Ошибка отсутствия подписки для функции"""
    pass


import asyncio
from openai import InternalServerError

async def retrieve_with_retry(client, file_id: str, max_attempts: int = 4, base_delay: float = 0.5):
    """
    Пытается получить информацию о файле из OpenAI API с помощью client.files.retrieve,
    повторяя до max_attempts раз при ошибке InternalServerError (код 502).
    """
    attempt = 0
    while attempt < max_attempts:
        try:
            # Пробуем получить информацию о файле
            file_info = await client.files.retrieve(file_id=file_id, timeout=3)
            return file_info
        except InternalServerError:
            print(traceback.format_exc())
            # Повтор возник из-за 502 Bad Gateway
            attempt += 1
            # Рассчитываем экспоненциальную задержку: base_delay * 2^(attempt-1)
            delay = base_delay * (2 ** (attempt - 1))
            # Ждём delay секунд перед следующей попыткой
            await asyncio.sleep(delay)
    # Если все попытки исчерпаны, выбрасываем ошибку дальше или возвращаем None
    raise RuntimeError(f"Не удалось получить файл {file_id} после {max_attempts} попыток")



async def get_thread_lock(thread_id: str) -> asyncio.Lock:
    # defaultdict вернёт существующий или создаст новый Lock
    return _thread_locks[thread_id]


load_dotenv(find_dotenv())
OPENAI_API_KEY: str | None = os.getenv("GPT_TOKEN") or os.getenv("OPENAI_API_KEY")
assistant_id = os.getenv("ASSISTANT_ID")
DEFAULT_IMAGE_MODEL = "gpt-image-1"
DEFAULT_IMAGE_SIZE = "1024x1024"

# --- вспомогательная фильтрация ---
def _strip_response_format(kwargs: dict) -> dict:
    # вычищаем response_format, если модель gpt-image-1
    if (kwargs.get("model") or DEFAULT_IMAGE_MODEL).startswith("gpt-image-1"):
        kwargs.pop("response_format", None)
    return kwargs


UNSUPPORTED_FOR_GPT_IMAGE = {"response_format", "style"}

def _strip_unsupported_params(kwargs: dict) -> dict:
    if (kwargs.get("model") or DEFAULT_IMAGE_MODEL).startswith("gpt-image-1"):
        for p in UNSUPPORTED_FOR_GPT_IMAGE:
            kwargs.pop(p, None)
    return kwargs


def _b64(b: bytes) -> str:
    """Возвращает Base64‑строку из байтов."""
    return base64.b64encode(b).decode()

def _b64decode(s: str) -> bytes:
    """Декодирует Base64‑строку в байты."""
    return base64.b64decode(s)

async def _retry(
    fn: Callable[..., Awaitable[Any]],
    *args,
    attempts: int = 6,
    backoff: float = 1.5,
    **kwargs,
):
    """Повторяет вызов *fn* с экспоненциальной задержкой при сетевых ошибках."""
    for attempt in range(1, attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except (APITimeoutError, APIConnectionError, APIStatusError, RateLimitError):
            if attempt == attempts:
                raise
            await asyncio.sleep(backoff ** attempt)
        except (AuthenticationError, PermissionDeniedError):
            raise  # ошибки неустранимы

class AsyncOpenAIImageClient:
    """Асинхронный обёртка над Image‑эндпоинтами OpenAI."""

    def __init__(
        self,
        *,
        api_key: str | None = OPENAI_API_KEY,
        organization: str | None = None,
        default_model: str = DEFAULT_IMAGE_MODEL,
        vision_model: str = "gpt-4o-mini",
    ) -> None:
        """Создаёт клиента с базовыми моделями изображения и vision."""
        self.client = AsyncOpenAI(api_key=api_key, organization=organization)
        self.default_model = default_model
        self.vision_model = vision_model  # используется в ImageChatSession

    # ---------- 1. GENERATE ----------
    async def generate(
            self,
            prompt: str,
            *,
            n: int = 1,
            size: str = DEFAULT_IMAGE_SIZE,
            quality: Literal["high", "medium", "low"] = "medium",
            user: str | None = None,
            model: str | None = None,
            images: Any | None = None,
    ) -> list[bytes]:
        model = model or self.default_model
        if images is None:
            params: dict[str, Any] = {
                "model": model,
                "prompt": prompt,
                "n": n,
                "size": size,
                "quality": quality,
                "response_format": "b64_json",
                "user": user,
                "timeout": 120
            }
            params = _strip_unsupported_params(params)
            rsp = await _retry(self.client.images.generate, **params)
            return [_b64decode(item.b64_json) for item in rsp.data]
        params: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "image": images[0],
            "timeout": 120
        }
        rsp = await _retry(self.client.images.edit, **params)
        return [_b64decode(item.b64_json) for item in rsp.data]





def _image_content(b: bytes, detail: str = "auto") -> dict:
    """Формирует словарь‑контент для изображения."""
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64(b)}"}, "detail": detail}



from os import getenv as _getenv
from db.models import Users
from db.repository import users_repository, subscriptions_repository, type_subscriptions_repository

api_key = OPENAI_API_KEY


class GPT:  # noqa: N801 – сохраняем оригинальное имя
    """Асинхронный помощник, работающий через Threads/Assistants API."""

    def __init__(self, assistant_id: str | None = assistant_id):
        """Инициализирует GPT-ассистента с необязательным *thread_id*."""
        self.assistant_id = assistant_id
        self.client = AsyncOpenAI(api_key=api_key)
        self.assistant = None
        # thread_id будет передаваться в методе send_message для каждого запроса
        self.vector_store_id: str | None = None

    async def _safe_create_run(self, *, thread_id: str, assistant_id: str,
                               instructions: str, model: str,
                               timeout: float, max_retry: int = 3):
        for attempt in range(max_retry):
            try:
                return await self.client.beta.threads.runs.create_and_poll(
                    thread_id=thread_id,
                    assistant_id=assistant_id,
                    instructions=instructions,
                    model=model,
                    timeout=timeout,
                )
            except BadRequestError as e:
                # если уже есть активный run — дождаться его завершения и повторить
                if "already has an active run" in str(e) and attempt < max_retry - 1:
                    await self._wait_for_active_run(thread_id)
                    continue
                # во всех остальных случаях пробросить ошибку дальше
                raise

    async def _ensure_assistant(self):
        """Ленивая загрузка объекта ассистента."""
        if self.assistant is None:
            self.assistant = await self.client.beta.assistants.retrieve(assistant_id=self.assistant_id)

    async def _ensure_thread(self, *, user_id: int, thread_id: str | None = None):
        """Гарантирует существование объекта thread: возвращает переданный или создаёт новый."""
        if thread_id is None:
            thread = await self._create_thread(user_id)
        else:
            thread = await self.client.beta.threads.retrieve(thread_id=thread_id)
        return thread

    async def _create_thread(self, user_id: int, type_assistant: str | None = "mental"):
        """Создаёт новый thread и сохраняет его в БД; возвращает созданный thread."""
        thread = await self.client.beta.threads.create()
        # Сохраняем идентификатор треда пользователю
        await users_repository.update_thread_id_by_user_id(user_id=user_id, thread_id=thread.id)
        return thread

    async def _sync_vector_store(self, thread_id: str, file_ids: list[str]) -> str:
        """
        Привязывает к thread единственный vector‑store,
        содержащий точно указанный набор file_ids.
        """
        thread = await self.client.beta.threads.retrieve(thread_id)

        # 1. получаем текущий vs, если он уже есть
        vs_ids = []
        if thread.tool_resources and thread.tool_resources.file_search:
            vs_ids = thread.tool_resources.file_search.vector_store_ids or []

        vs_id = vs_ids[0] if vs_ids else None

        # 2. создаём VS при отсутствии
        if vs_id is None:
            vs = await self.client.vector_stores.create(
                name=f"vs-{thread_id}",
                file_ids=file_ids,
            )
            vs_id = vs.id

            await self.client.beta.threads.update(
                thread_id=thread_id,
                tool_resources={"file_search": {"vector_store_ids": [vs_id]}},
            )
        else:
            # 3. синхронизация существующего хранилища
            current_ids = {
                f.id
                for f in (await self.client.vector_stores.files.list(vs_id)).data
            }

            # удалить лишние
            for fid in current_ids - set(file_ids):
                await self.client.vector_stores.files.delete(vector_store_id=vs_id, file_id=fid)

            # добавить недостающие
            for fid in set(file_ids) - current_ids:
                await self.client.vector_stores.files.create(
                    vector_store_id=vs_id,
                    file_id=fid,
                )

        # 4. ждём завершения индексации
        while (await self.client.vector_stores.retrieve(vs_id)).status != "completed":
            await asyncio.sleep(0.3)

        return vs_id

    async def send_message(
        self,
        user_id: int,
        thread_id: str | None = None,
        *,
        with_audio_transcription: bool = False,
        text: str | None = None,
        image_bytes: Sequence[io.BytesIO] | None = None,
        document_bytes: Sequence[tuple[io.BytesIO, str, str]] | None = None,
        document_type: str | None = None,
        audio_bytes: io.BytesIO | None = None,
        user_data: Users | None = None,
    ):
        from bot import logger
        from settings import get_weekday_russian
        """Отправляет пользовательский запрос с опциональными вложениями."""
        # При каждом запросе обновляем текущий thread, если он передан явно
        await self._ensure_assistant()
        if thread_id is None:
            thread = await self._ensure_thread(user_id=user_id, thread_id=thread_id)
            thread_id = thread.id
        lock = await get_thread_lock(thread_id)
        async with lock:  # ⬅️  ВСЕ операции с thread – под замком
            await self._wait_for_active_run(thread_id)

            # about_user = self._build_about_user(user_data)
            user = await users_repository.get_user_by_user_id(user_id=user_id)
            about_user = user.context
            text = (text or "Вот информация")
            # print(document_bytes)
            if not any([text, image_bytes, document_bytes, audio_bytes]):
                return None
            # print(text)
            content, attachments, file_ids = await self._build_content(
                text,
                image_bytes=image_bytes,
                document_bytes=document_bytes,
                audio_bytes=audio_bytes,
            )
            # print(content)
            if file_ids:
                await self._sync_vector_store(thread_id, file_ids)
            # print(attachments)
            try:
                await self.client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=content,
                    attachments=attachments or None,
                    timeout=15.0,
                )
                # 4. запускаем новый run и ждём результата
                run = await self._safe_create_run(
                    thread_id=thread_id,
                    assistant_id=self.assistant.id,
                    instructions=f"Сегодня - {get_current_datetime_string()}\n\n по Москве.День недели - {get_weekday_russian()} "
                                 f"Учитывай эту информацию,"
                                 f" если пользователь просит поставить уведомление\n\nОсновные инструкции:\n" + self.assistant.instructions +
                                 f"\n\nИнформация о пользователе:\n{about_user}" if about_user else f"Сегодня - {get_current_datetime_string()}\n\n"
                                                                                                    f" по Москве.День недели - {get_weekday_russian()}" +
                                                               self.assistant.instructions,
                    model=user.model_type,
                    timeout=15.0,
                )
                # print("Сегодня - ", get_current_datetime_string())
                # ---------------- NEW: обработка image‑tools ----------------
                if run.status == "requires_action":
                    from bot import main_bot
                    user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user.user_id)
                    sub_types = await type_subscriptions_repository.select_all_type_subscriptions()
                    if user_sub is None:
                        from test_bot import test_bot
                        from settings import sub_text
                        await test_bot.send_message(chat_id=user.user_id,
                                                    text="🚨К сожалению, данная функция, которую ты"
                                                " пытаешься использовать доступна только по подписке\n\n" + sub_text,
                                                    reply_markup=subscriptions_keyboard(sub_types).as_markup())
                        raise NoSubscription(f"User {user.user_id} dont has active subscription")
                    delete_message = None
                    for tc in run.required_action.submit_tool_outputs.tool_calls:
                        if tc.function.name == "search_web":
                            delete_message = await main_bot.send_message(text="🔍Начал поиск в интернете, анализирую страницы...",
                                                                         chat_id=user.user_id)
                        elif tc.function.name == "add_notification":
                            delete_message = await main_bot.send_message(
                                text="🖌Начал настраивать напоминание, это не займет много времени...",
                                chat_id=user.user_id)
                        else:
                            if user_sub.photo_generations <= 0:
                                return "Дорогой друг, у тебя закончились генерации изображений по твоему плану"
                            delete_message = await main_bot.send_message(chat_id=user.user_id,
                                                                         text="🎨Начал работу над изображением, немного магии…")
                        break
                    try:
                        result = await process_assistant_run(self.client, run, thread_id, user_id=user.user_id)
                        result_images = result.get("final_images")
                        web_answer: str = result.get("web_answer")
                        notification: str = result.get("notif_answer")
                        if len(result_images) == 0 and web_answer is None and notification is None:
                            try:
                                await delete_message.delete()
                            finally:
                                # from bot import logger
                                # logger.error("Не смогли сгенерировать изображение или обработать запрос😔\n\nВозможно,"
                                #         " ты попросил что-то, что выходит за рамки норм", result)
                                return ("Не смогли сгенерировать изображение или обработать запрос😔\n\nВозможно,"
                                        " ты попросил что-то, что выходит за рамки норм")
                        messages = await self.client.beta.threads.messages.list(thread_id=thread_id)
                        await delete_message.delete()
                        first_msg = messages.data[0]
                        if web_answer:
                            return sanitize_with_links(web_answer)
                        if notification:
                            return sanitize_with_links(notification)
                        elif len(result_images) != 0:
                            return {"text": first_msg.content[0].text.value if hasattr(first_msg.content[0], "text") else "Сгенерировал изображение",
                                    "images": result_images}
                    except Exception:
                        print(traceback.format_exc())
                        await delete_message.delete()
                        from bot import logger
                        logger.log(
                            "GPT_ERROR",
                            f"{user_id} | Ошибка в ответе gpt: {traceback.format_exc()}"
                        )
                        print_log(message=f"{user_id} | Ошибка в ответе gpt: {traceback.format_exc()}")
                        return ("Произошла непредвиденная ошибка, попробуй еще раз!"
                                " Твой запрос может содержать контент, который"
                                " не разрешен нашей системой безопасности")
                if run.status == "completed":
                    messages = await self.client.beta.threads.messages.list(thread_id=thread_id)
                    if messages.data[0].content[0].type == "image_file":
                        # print(messages.data[0].content[0].image_file)
                        image_file = messages.data[0].content[0].image_file
                        file_id = image_file.file_id
                        file_obj = await self.client.files.retrieve(file_id=file_id)
                        # pprint.pprint(file_obj.json)
                        data = await self.client.files.content(file_id)
                        return {"filename": file_obj.filename + ".png", "bytes": await data.aread()}
                    # message_text = _sanitize(
                    #     messages.data[0].content[0].text.value
                    # )
                    # pprint.pprint(messages.data[0].attachments)
                    if messages.data[0].attachments:
                        # print(messages.data[0].content[0].text.value)
                        for content in messages.data[0].attachments:
                            # print(content)
                            file_id = content.file_id
                            file_obj = await self.client.files.retrieve(file_id=file_id)
                            data = await self.client.files.content(file_id)
                            return {"filename": file_obj.filename, "bytes": await data.aread()}
                    # files = messages.data[0].file_ids
                    # message_text = re.sub(r"【[^】]+】", "", message_text).strip()
                    message_text = messages.data[0].content[0].text.value
                    if with_audio_transcription:
                        audio_data = await self.generate_audio_by_text(message_text)
                        return sanitize_with_links(message_text), audio_data
                    return sanitize_with_links(message_text)
                # print(run.json)
                logger.log(
                    "GPT_ERROR",
                    f"ЗАКОНЧИЛИСЬ БАБКИ или другая ошибка gpt: {run.json()}"
                )
                return ("Произошла непредвиденная ошибка, попробуй еще раз! Cейчас наблюдаются сбои в системе")
            except NoSubscription:  # 1. пропускаем тарифные ошибки
                raise
            except Exception:
                traceback.print_exc()
                try:
                    await self.client.beta.threads.runs.cancel(run_id=run.id, thread_id=thread_id)
                finally:
                    # При фатальной ошибке переинициализируем клиента, чтобы попытаться восстановить соединение
                    await self._reset_client()
                    logger.log(
                        "GPT_ERROR",
                        f"{user_id} | Ошибка в ответе gpt: {traceback.format_exc()}"
                    )
                    print_log(message=f"{user_id} | Ошибка в ответе gpt: {traceback.format_exc()}")
                    return ("Произошла непредвиденная ошибка, попробуй еще раз! Твой запрос может содержать"
                            " контент, который не разрешен нашей системой безопасности")

    # -------- вспомогательные методы --------
    @staticmethod
    async def generate_audio_by_text(text: str) -> io.BytesIO:
        """TTS‑синтез ответа в mp3 через /audio/speech."""
        url = "https://api.openai.com/v1/audio/speech"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "gpt-4o-mini-tts",
            "input": text,
            "voice": "shimmer",
            "instructions": "Speak dramatic",
            "response_format": "mp3",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=30) as response:
                if response.status == 200:
                    return io.BytesIO(await response.read())
                raise RuntimeError(f"TTS error {response.status}: {await response.text()}")

    @staticmethod
    async def transcribe_audio(audio_bytes: io.BytesIO, language: str = "ru") -> str:
        """Возвращает текстовую расшифровку аудио через Whisper."""
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {api_key}"}

        audio_bytes.name = "audio.mp3"
        data = {"file": audio_bytes, "model": "whisper-1", "language": language}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data, timeout=60) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("text", "")
                raise RuntimeError(f"Transcription error {response.status}: {await response.text()}")

    @staticmethod
    def _build_about_user(user: Users | None) -> str:
        """Формирует префикс с данными пользователя для контекстного ответа."""
        if user is None:
            return ""
        parts: list[str] = []
        if user.name not in (None, "NoName"):
            parts.append(f"Имя: {user.name}")
        if user.gender:
            parts.append(f"Пол: {user.gender}")
        if user.age:
            parts.append(f"Диапазон возраста: {user.age}")

        if not parts:
            return ""

        info = "\n".join(parts)
        prefix = (
            "Отвечай с учетом следующей информации о пользователе (используй разные конструкции обращения "
            "к пользователю, например,  иногда по имени, иногда просто по местоимению). Если ты видишь, что в "
            "предыдущем сообщении ты обращался по имени, то сейчас по имени не обращайся, а также не надо каждый "
            "раз приветствовать.\n\n"
        )
        return prefix + info + "\n\n"

    async def _build_content(
            self,
            text: str,
            *,
            image_bytes: Sequence[io.BytesIO] | None,
            document_bytes: Sequence[tuple[io.BytesIO, str, str]] | None,
            audio_bytes: io.BytesIO | None,
    ) -> tuple[list[dict], list[dict], list[str]]:
        content: list[dict] = []
        attachments: list[dict] = []
        doc_file_ids: list[str] = []

        # 1. транскрипт аудио (не трогаем...)
        # 2. текст
        image_names = []
        # 3. изображения
        if image_bytes:
            for idx, img_io in enumerate(image_bytes):
                img_io.seek(0)
                img_file = await self.client.files.create(
                    file=(f"image_{idx}.png", img_io, "image/png"),
                    purpose="vision",
                )
                while True:
                    if img_file.status in ("uploaded", "processed", "error"):
                        break
                    await asyncio.sleep(0.3)
                while True:
                    try:
                        # print("попытка")
                        file_info = await retrieve_with_retry(self.client, file_id=img_file.id)
                    except RuntimeError:
                        from bot import logger
                        logger.log(
                            "GPT_ERROR",
                            f" Ошибка в ответе gpt: {traceback.format_exc()}"
                        )
                        print_log(message=f" Ошибка в ответе gpt: {traceback.format_exc()}")
                        # Если не удалось получить файл после retry, возвращаем пользователю понятное сообщение
                        return [{"type": "text", "text": text}], [], []
                    # Статус может отличаться в разных SDK, здесь проверяем конечный
                    # print(file_info.status)
                    if getattr(file_info, "status", None) in ("uploaded", "processing_complete", "ready", "processed"):
                        break
                    await asyncio.sleep(0.2)
                # (Опционально) Можно добавить ещё небольшую задержку
                await asyncio.sleep(1)  # даём Vision-движку немного «вздохнуть»

                image_names.append(f"image_{idx}.png")
                content.append({
                    "type": "image_file",
                    "image_file": {"file_id": img_file.id},
                })
                # print(image_names)

            text += f"\n\nВот названия изображений: {', '.join(image_names)}"

        # 4. документы
        if document_bytes:
            text += "\n\nВот названия файлов, которые я прикрепил:\n"
            for idx, (doc_io, file_name, mime_ext) in enumerate(document_bytes):
                doc_io.seek(0)
                doc_file = await self.client.files.create(
                    file=(f"{file_name}", doc_io, f"application/{mime_ext}"),
                    purpose="assistants",
                )
                text += f"{file_name} "
                doc_file_ids.append(doc_file.id)
                attachments.append({
                    "file_id": doc_file.id,
                    "tools": [{"type": "file_search"}],
                })
        #
        content.append({"type": "text", "text": f"Сегодня - {get_current_datetime_string()}\n\n по Москве.\n\n" + text})
        return content, attachments, doc_file_ids

    async def _wait_for_active_run(
        self,
        thread_id: str,
        poll_interval: float = 0.5,
    ) -> None:
        """
        Блокирует выполнение, пока в thread есть активный run.
        Обеспечивает последовательную обработку запросов (очередь).
        """
        ACTIVE = {"queued", "in_progress", "requires_action", "cancelling", "active"}
        retries = 360
        while retries > 0:
            runs = await self.client.beta.threads.runs.list(
                thread_id=thread_id,
                limit=100,
                order="desc",  # последний первым
            )
            if any(r.status in ACTIVE for r in runs.data):
                await asyncio.sleep(poll_interval)
                retries -= 1
                continue
            break
        else:
            runs = await self.client.beta.threads.runs.list(
                thread_id=thread_id,
                limit=100,
                order="desc",  # последний первым
            )
            for run in runs.data:
                if any(r.status in ACTIVE for r in runs.data):
                    await self.client.beta.threads.runs.cancel(run_id=run.id, timeout=10)

    async def _reset_client(self):
        """Переинициализирует клиента OpenAI и сбрасывает кеш ассистента."""
        self.client = AsyncOpenAI(api_key=api_key)
        self.assistant = None


async def dispatch_tool_call(tool_call, image_client, user_id: int) -> Any:
    """
    Принимает как Pydantic‑объект RequiredActionFunctionToolCall,
    так и старый словарь (для обратной совместимости).
    """
    # --- 1. Извлекаем имя и аргументы ---
    if hasattr(tool_call, "function"):                         # новый формат
        name = tool_call.function.name
        args_raw = tool_call.function.arguments
    else:                                                      # старый формат (dict)
        name = tool_call.get("name") or tool_call.get("function", {}).get("name")
        args_raw = tool_call.get("arguments") or tool_call.get("function", {}).get("arguments")

    # --- 2. Приводим arguments к dict ---
    import json
    if isinstance(args_raw, dict):
        args = args_raw
    else:
        try:
            args = json.loads(args_raw)
        except json.JSONDecodeError:
            print("\n\n")
            # print(args_raw)
            print("\n\n")
            # например, обрезать до первого `}` и допarse
            first_obj = args_raw.split('}', 1)[0] + '}'
            args = json.loads(first_obj)
    from bot import main_bot
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    photo_bytes = []
    if name == "add_notification":
        # print("\n\nadd_notification\n\n")
        when_send_str, text_notification = args.get("when_send_str"), args.get("text_notification")
        # print(args)
        # print("Дата отправки:", when_send_str)
        try:
            await schedule_notification(user_id=user.user_id,
                                        when_send_str=when_send_str,
                                        text_notification=text_notification)
            return f"Отлично, добавили уведомление на {when_send_str} по московскому времени\n\nТекст уведомления: {text_notification}"
        except NotificationSchedulerError:
            print(traceback.format_exc())
            return "Нельзя запланировать уведомление на прошлое время или неверный формат даты/времени"
    if name == "search_web":
        # print("\n\nsearch_web\n\n")
        query = args.get("query") or ""
        # вызываем агент из web_search_agent.py
        result = await web_search_agent.search_prompt(query)
        # возвращаем результат модели как plain text
        return result
    if user.last_image_id is not None:
        for photo_id in user.last_image_id.split(", "):
            # print(photo_id)
            photo_bytes_io = io.BytesIO()
            await main_bot.download(photo_id, destination=photo_bytes_io)
            photo_bytes_io.seek(0)
            photo_bytes.append(photo_bytes_io.read())
    # --- 3. Диспатчинг ---
    if name == "generate_image":
        # print("generate_image")
        # print(args.get("edit_existing_photo"))
        try:
            kwargs: dict[str, Any] = {
                "prompt": args["prompt"],
                "n": args.get("n", 1),
                "size": args.get("size", DEFAULT_IMAGE_SIZE),
                "quality": args.get("quality", "low"),
            }
            # print("\n\n\nИзменять?", args.get("edit_existing_photo"))
            if args.get("edit_existing_photo"):
                kwargs["images"] = [("image.png", io.BytesIO(photo), "image/png") for photo in photo_bytes]
            return await image_client.generate(**kwargs)
        except:
            return []

    if name == "edit_image_only_with_peoples":
        # print("edit_image_only_with_peoples")
        # print(args.get("prompt"))
        # print(args)
        try:
            prompt = args.get("prompt", "").strip()
            prompt = prompt[:400]  # максимум 200 символов
            # при необходимости — удалить не-ASCII символы
            prompt = prompt.encode('ascii', 'ignore').decode()
            if not prompt:
                # либо возвращать понятную ошибку, либо пропускать этот tool-call
                return []
            return [await generate_image_bytes(prompt=args.get("prompt"), ratio=args.get("ratio"),
                                               images=photo_bytes if len(photo_bytes) <= 3 else photo_bytes[:3])]
        except RuntimeError as e:
            print(f"Runway task failed for prompt «{prompt}»: {e}")
            return []
        except Exception as e:
            from bot import logger
            logger.log(
                "GPT_ERROR",
                f"{user_id} | Ошибка в ответе gpt: {traceback.format_exc()}"
            )
            print_log(message=f"{user_id} | Ошибка в ответе gpt: {traceback.format_exc()}")
            return []
    return None


async def process_assistant_run(
    client: AsyncOpenAI,
    run,
    thread_id: str,
    user_id: int,
    image_client: Optional[AsyncOpenAIImageClient] = None,
):
    """Выполняет все tool‑calls ассистента и передаёт результаты."""
    if run.status != "requires_action" or run.required_action.type != "submit_tool_outputs":
        return
    image_client = image_client or AsyncOpenAIImageClient()
    outputs = []
    final_images = []
    web_answer = None
    text_answer = None
    for tc in run.required_action.submit_tool_outputs.tool_calls:
        if tc.function.name == "search_web" or tc.function.name == "add_notification":
            text_answer = await dispatch_tool_call(tc, image_client, user_id=user_id)
            outputs.append({"tool_call_id": tc.id, "output": json.dumps({"text": web_answer})})
            continue
        images = (await dispatch_tool_call(tc, image_client, user_id=user_id))
        final_images.extend(images)
        if images is None:
            outputs.append({"tool_call_id": tc.id, "output": "ignored"})
            continue
        # сохраняем изображения как файлы
        file_ids = []
        # if images[1] == "openai":
        for idx, img in enumerate(images):
            file = await client.files.create(file=(f"result_{idx}.png", io.BytesIO(img), "image/png"), purpose="vision")
            file_ids.append(file.id)
        outputs.append({
            "tool_call_id": tc.id,
            "output": json.dumps({"file_ids": file_ids})
        })
    # print(final_images)
    await client.beta.threads.runs.submit_tool_outputs(thread_id=thread_id, run_id=run.id, tool_outputs=outputs)
    # print("ура, картинка сделана")
    await _await_run_done(client=client , thread_id=thread_id, run_id=run.id)
    return {"final_images": final_images, "web_answer": web_answer, "notif_answer": text_answer}
    # return images


async def _await_run_done(client, thread_id: str, run_id: str) -> None:
    TERMINAL = {"completed", "failed", "cancelled", "expired"}
    while True:
        run = await client.beta.threads.runs.retrieve(
            thread_id=thread_id, run_id=run_id
        )
        if run.status in TERMINAL:
            return
        await asyncio.sleep(0.5)

