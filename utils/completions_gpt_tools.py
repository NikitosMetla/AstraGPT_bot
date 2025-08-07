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
from utils.combined_gpt_tools import AsyncOpenAIImageClient, NoSubscription

# completions_gpt_tools.py

_thread_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def get_thread_lock(thread_id: str) -> asyncio.Lock:
    # defaultdict вернёт существующий или создаст новый Lock
    return _thread_locks[thread_id]


load_dotenv(find_dotenv())
OPENAI_API_KEY: str | None = os.getenv("GPT_TOKEN") or os.getenv("OPENAI_API_KEY")
DEFAULT_IMAGE_MODEL = "gpt-image-1"
DEFAULT_IMAGE_SIZE = "1024x1024"

# --- вспомогательные функции ---
def _b64(b: bytes) -> str:
    """Возвращает Base64‑строку из байтов."""
    return base64.b64encode(b).decode()

def _b64decode(s: str) -> bytes:
    """Декодирует Base64‑строку в байты."""
    return base64.b64decode(s)

async def _retry(
    fn: Callable[..., Awaitable[Any]],
    *args,
    attempts: int = 6,
    backoff: float = 1.5,
    **kwargs,
):
    """Повторяет вызов *fn* с экспоненциальной задержкой при сетевых ошибках."""
    for attempt in range(1, attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except (APITimeoutError, APIConnectionError, APIStatusError, RateLimitError):
            if attempt == attempts:
                raise
            await asyncio.sleep(backoff ** attempt)
        except (AuthenticationError, PermissionDeniedError):
            raise  # ошибки неустранимы


class ThreadMessagesManager:
    """Класс для управления сообщениями через OpenAI threads для Chat Completions API"""
    
    def __init__(self, client: AsyncOpenAI):
        self.client = client
    
    async def save_messages_to_thread(self, thread_id: str, user_message: str, assistant_response: str):
        """Сохраняет пользовательское сообщение и ответ ассистента в OpenAI thread"""
        try:
            # Добавляем сообщение пользователя
            await self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=user_message
            )
            
            # Добавляем ответ ассистента
            await self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="assistant",
                content=assistant_response
            )
        except Exception as e:
            print(f"Ошибка при сохранении сообщений в thread {thread_id}: {e}")
    
    async def get_thread_messages(self, thread_id: str, limit: int = 10) -> list[dict]:
        """Загружает последние сообщения из OpenAI thread и форматирует их для Chat Completions API"""
        try:
            messages = await self.client.beta.threads.messages.list(
                thread_id=thread_id,
                limit=limit * 2,  # учитываем что у нас есть и user и assistant сообщения
                order="desc"
            )
            
            # Преобразуем в формат для Chat Completions API
            formatted_messages = []
            for message in reversed(messages.data):
                if message.role in ["user", "assistant"]:
                    content = ""
                    if hasattr(message.content[0], 'text'):
                        content = message.content[0].text.value
                    elif hasattr(message.content[0], 'image_file'):
                        content = "изображение было обработано"
                    
                    formatted_messages.append({
                        "role": message.role,
                        "content": content
                    })
            
            # Ограничиваем до последних limit пар сообщений
            if len(formatted_messages) > limit * 2:
                formatted_messages = formatted_messages[-(limit * 2):]
            
            return formatted_messages
            
        except Exception as e:
            print(f"Ошибка при загрузке сообщений из thread {thread_id}: {e}")
            return []
    
    async def ensure_thread_exists(self, thread_id: str | None = None) -> str:
        """Проверяет существование thread или создает новый через OpenAI API"""
        if thread_id:
            try:
                await self.client.beta.threads.retrieve(thread_id=thread_id)
                return thread_id
            except:
                # Если thread не найден, создаем новый
                pass
        
        # Создаем новый thread через OpenAI API
        thread = await self.client.beta.threads.create()
        return thread.id


class GPTCompletions:  # noqa: N801 – сохраняем схожее имя с оригиналом
    """Помощник через Chat Completions API вместо Assistant API."""

    def __init__(self):
        """Инициализирует GPT-помощника через Chat Completions API."""
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.messages_manager = ThreadMessagesManager(self.client)

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
        user_data = None,
    ):
        from bot import logger
        from settings import get_weekday_russian
        from db.repository import users_repository, subscriptions_repository, type_subscriptions_repository
        
        """Отправляет пользовательский запрос с опциональными вложениями через Chat Completions API."""
        
        # Получаем данные о пользователе и определяем актуальный thread
        user = await users_repository.get_user_by_user_id(user_id=user_id)

        # Если thread_id явно не передан, пытаемся взять его из базы пользователя
        if thread_id is None:
            if user.standard_ai_threat_id:
                # Используем уже существующий thread пользователя (создаём если вдруг удалён)
                thread_id = await self.messages_manager.ensure_thread_exists(user.standard_ai_threat_id)
            else:
                # Создаём новый thread и сохраняем в базу
                thread_id = await self.messages_manager.ensure_thread_exists()
                await users_repository.update_thread_id_by_user_id(user_id=user_id, thread_id=thread_id)
        else:
            # Убедимся, что указанный thread существует, иначе создадим новый
            thread_id = await self.messages_manager.ensure_thread_exists(thread_id)

        lock = await get_thread_lock(thread_id)
        async with lock:  # ⬅️  ВСЕ операции с thread – под замком
            try:
                # Информация о пользователе уже получена выше
                about_user = user.context if user else ""
                
                text = (text or "Вот информация")
                
                if not any([text, image_bytes, document_bytes, audio_bytes]):
                    return None

                # Формируем контент сообщения
                content_parts = []
                attachments = []
                
                # Обрабатываем изображения
                if image_bytes:
                    for idx, img_io in enumerate(image_bytes):
                        img_io.seek(0)
                        img_data = img_io.read()
                        base64_image = base64.b64encode(img_data).decode('utf-8')
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        })

                # Добавляем текст
                full_text = f"Сегодня - {get_current_datetime_string()}\n\n по Москве.\n\n"
                if about_user:
                    full_text += f"Информация о пользователе:\n{about_user}\n\n"
                full_text += text

                content_parts.insert(0, {
                    "type": "text", 
                    "text": full_text
                })

                # Загружаем историю сообщений
                history_messages = await self.messages_manager.get_thread_messages(thread_id, limit=10)
                
                # Формируем системное сообщение
                system_message = {
                    "role": "system",
                    "content": f"Сегодня - {get_current_datetime_string()} по Москве. День недели - {get_weekday_russian()}. "
                               f"Ты - умный помощник AstraGPT. Помогай пользователю с различными задачами."
                }

                # Формируем полный список сообщений для API
                messages = [system_message] + history_messages + [{
                    "role": "user",
                    "content": content_parts if len(content_parts) > 1 else content_parts[0]["text"]
                }]

                # Определяем доступные функции
                from settings import tools

                # Отправляем запрос к Chat Completions API
                response = await _retry(
                    self.client.chat.completions.create,
                    model=user.model_type if user else "gpt-4o-mini",
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    timeout=30.0
                )

                message_response = response.choices[0].message
                
                # Обрабатываем tool calls если они есть
                if message_response.tool_calls:
                    # Проверяем подписку пользователя
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
                    
                    # Показываем индикатор загрузки
                    delete_message = None
                    from bot import main_bot
                    
                    tool_call = message_response.tool_calls[0]
                    if tool_call.function.name == "search_web":
                        delete_message = await main_bot.send_message(text="🔍Начал поиск в интернете, анализирую страницы...",
                                                                     chat_id=user.user_id)
                    elif tool_call.function.name == "add_notification":
                        delete_message = await main_bot.send_message(
                            text="🖌Начал настраивать напоминание, это не займет много времени...",
                            chat_id=user.user_id)
                    else:
                        if user_sub.photo_generations <= 0:
                            return "Дорогой друг, у тебя закончились генерации изображений по твоему плану"
                        delete_message = await main_bot.send_message(chat_id=user.user_id,
                                                                     text="🎨Начал работу над изображением, немного магии…")
                    
                    try:
                        # Обрабатываем tool calls
                        tool_results = await process_tool_calls(message_response.tool_calls, user_id=user.user_id)
                        result_images = tool_results.get("final_images", [])
                        web_answer = tool_results.get("web_answer")
                        notification = tool_results.get("notif_answer")
                        
                        if len(result_images) == 0 and web_answer is None and notification is None:
                            await delete_message.delete()
                            return ("Не смогли сгенерировать изображение или обработать запрос😔\n\nВозможно,"
                                    " ты попросил что-то, что выходит за рамки норм")
                        
                        await delete_message.delete()
                        
                        if web_answer:
                            # Сохраняем в thread
                            await self.messages_manager.save_messages_to_thread(thread_id, text, web_answer)
                            return sanitize_with_links(web_answer)
                        
                        if notification:
                            # Сохраняем в thread
                            await self.messages_manager.save_messages_to_thread(thread_id, text, notification)
                            return sanitize_with_links(notification)
                        
                        elif len(result_images) != 0:
                            final_text = "Сгенерировал изображение"
                            # Сохраняем в thread
                            await self.messages_manager.save_messages_to_thread(thread_id, text, final_text)
                            return {"text": final_text, "images": result_images}
                            
                    except Exception:
                        print(traceback.format_exc())
                        await delete_message.delete()
                        logger.log(
                            "GPT_ERROR",
                            f"{user_id} | Ошибка в ответе gpt: {traceback.format_exc()}"
                        )
                        print_log(message=f"{user_id} | Ошибка в ответе gpt: {traceback.format_exc()}")
                        return ("Произошла непредвиденная ошибка, попробуй еще раз!"
                                " Твой запрос может содержать контент, который"
                                " не разрешен нашей системой безопасности")
                else:
                    # Обычный ответ без tool calls
                    response_text = message_response.content
                    
                    # Сохраняем в thread
                    await self.messages_manager.save_messages_to_thread(thread_id, text, response_text)
                    
                    if with_audio_transcription:
                        audio_data = await self.generate_audio_by_text(response_text)
                        return sanitize_with_links(response_text), audio_data
                    
                    return sanitize_with_links(response_text)

            except NoSubscription:  # 1. пропускаем тарифные ошибки
                raise
            except Exception:
                traceback.print_exc()
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
        """TTS‑синтез ответа в mp3 через /audio/speech."""
        url = "https://api.openai.com/v1/audio/speech"
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
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
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

        audio_bytes.name = "audio.mp3"
        data = {"file": audio_bytes, "model": "whisper-1", "language": language}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data, timeout=60) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("text", "")
                raise RuntimeError(f"Transcription error {response.status}: {await response.text()}")

    async def _reset_client(self):
        """Переинициализирует клиента OpenAI."""
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.messages_manager = ThreadMessagesManager(self.client)


async def dispatch_tool_call_completions(tool_call, user_id: int) -> Any:
    """
    Обрабатывает tool call для Chat Completions API
    """
    from bot import main_bot
    from db.repository import users_repository
    
    # Извлекаем имя и аргументы функции
    name = tool_call.function.name
    args_raw = tool_call.function.arguments
    
    # Парсим аргументы
    if isinstance(args_raw, dict):
        args = args_raw
    else:
        try:
            args = json.loads(args_raw)
        except json.JSONDecodeError:
            # Попытка исправить неполный JSON
            first_obj = args_raw.split('}', 1)[0] + '}'
            args = json.loads(first_obj)
    
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    photo_bytes = []
    
    if name == "add_notification":
        when_send_str, text_notification = args.get("when_send_str"), args.get("text_notification")
        try:
            await schedule_notification(user_id=user.user_id,
                                        when_send_str=when_send_str,
                                        text_notification=text_notification)
            return f"Отлично, добавили уведомление на {when_send_str} по московскому времени\n\nТекст уведомления: {text_notification}"
        except NotificationSchedulerError:
            print(traceback.format_exc())
            return "Нельзя запланировать уведомление на прошлое время или неверный формат даты/времени"
    
    if name == "search_web":
        query = args.get("query") or ""
        result = await web_search_agent.search_prompt(query)
        return result
    
    # Получаем последние изображения пользователя для редактирования
    if user.last_image_id is not None:
        for photo_id in user.last_image_id.split(", "):
            photo_bytes_io = io.BytesIO()
            await main_bot.download(photo_id, destination=photo_bytes_io)
            photo_bytes_io.seek(0)
            photo_bytes.append(photo_bytes_io.read())
    
    if name == "generate_image":
        try:
            image_client = AsyncOpenAIImageClient()
            kwargs: dict[str, Any] = {
                "prompt": args["prompt"],
                "n": args.get("n", 1),
                "size": args.get("size", DEFAULT_IMAGE_SIZE),
                "quality": args.get("quality", "low"),
            }
            
            if args.get("edit_existing_photo"):
                kwargs["images"] = [("image.png", io.BytesIO(photo), "image/png") for photo in photo_bytes]
            
            return await image_client.generate(**kwargs)
        except:
            return []

    if name == "edit_image_only_with_peoples":
        try:
            prompt = args.get("prompt", "").strip()
            prompt = prompt[:400]  # максимум 400 символов
            prompt = prompt.encode('ascii', 'ignore').decode()
            if not prompt:
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


async def process_tool_calls(tool_calls, user_id: int):
    """Обрабатывает все tool calls и возвращает результаты"""
    final_images = []
    web_answer = None
    text_answer = None
    
    for tool_call in tool_calls:
        if tool_call.function.name in ["search_web", "add_notification"]:
            text_answer = await dispatch_tool_call_completions(tool_call, user_id=user_id)
            web_answer = text_answer
            continue
        
        images = await dispatch_tool_call_completions(tool_call, user_id=user_id)
        if images:
            final_images.extend(images)
    
    return {"final_images": final_images, "web_answer": web_answer, "notif_answer": text_answer}

