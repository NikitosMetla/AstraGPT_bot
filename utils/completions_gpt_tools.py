# gpt_completions.py

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import traceback
from collections import defaultdict
from typing import Any, Awaitable, Callable, Optional, Sequence, Dict, List, Tuple

import aiohttp
from dotenv import find_dotenv, load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
    BadRequestError,
)

from settings import get_current_datetime_string, print_log, get_current_bot
from data.keyboards import subscriptions_keyboard, more_generations_keyboard, delete_notification_keyboard
from utils import web_search_agent
from utils.create_notification import (
    schedule_notification,
    NotificationLimitError,
    NotificationFormatError,
    NotificationDateTooFarError,
    NotificationDateInPastError,
    NotificationPastTimeError,
    NotificationTextTooShortError,
    NotificationTextTooLongError,
)
from utils.gpt_images import AsyncOpenAIImageClient
from utils.new_fitroom_api import FitroomClient
from utils.parse_gpt_text import sanitize_with_links
from utils.runway_api import generate_image_bytes

from db.models import Users
from db.repository import (
    users_repository,
    subscriptions_repository,
    type_subscriptions_repository,
    generations_packets_repository,
    notifications_repository, dialogs_messages_repository,
)
from db.models import DialogsMessages

# --- глобальные переменные и инициализация ---

load_dotenv(find_dotenv())
OPENAI_API_KEY: str | None = os.getenv("GPT_TOKEN") or os.getenv("OPENAI_API_KEY")
DEFAULT_IMAGE_MODEL = "gpt-image-1"
DEFAULT_IMAGE_SIZE = "1024x1024"

_thread_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

class NoSubscription(Exception):
    pass

class NoGenerations(Exception):
    pass

async def get_thread_lock(user_key: str) -> asyncio.Lock:
    return _thread_locks[user_key]

def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()

async def _retry(
    fn: Callable[..., Awaitable[Any]],
    *args,
    attempts: int = 6,
    backoff: float = 1.5,
    **kwargs,
):
    for attempt in range(1, attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except (APITimeoutError, APIConnectionError, APIStatusError, RateLimitError):
            if attempt == attempts:
                raise
            await asyncio.sleep(backoff ** attempt)
        except (AuthenticationError, PermissionDeniedError):
            raise

# --- Помощники по аудио ---

async def tts_generate_audio_mp3(text: str) -> io.BytesIO:
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

# --- Адаптация tools к Chat Completions ---

def _tools_for_chat_completions(tools: List[dict]) -> List[dict]:
    conv = []
    for t in tools:
        conv.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description") or "",
                "parameters": t.get("parameters") or {"type": "object", "properties": {}},
                "strict": t.get("strict", False),
            }
        })
    return conv

# --- Сохранение/загрузка истории ---

class HistoryStore:
    def __init__(self):
        self.repo = dialogs_messages_repository

    async def append(self, user_id: int, payload: dict):
        await self.repo.add_message(user_id=user_id, message=payload)

    async def load(self, user_id: int) -> List[DialogsMessages]:
        return await self.repo.get_messages_by_user_id(user_id=user_id)

# --- Маппинг истории в Chat Completions messages ---

def _map_history_to_chat_messages(items: List[DialogsMessages]) -> List[dict]:
    msgs: List[dict] = []
    for itm in items:
        try:
            payload = itm.message
            t = payload.get("type")
            if t == "human":
                parts = (payload.get("additional_kwargs") or {}).get("content_parts")
                if parts and isinstance(parts, list):
                    msgs.append({"role": "user", "content": parts})
                else:
                    msgs.append({"role": "user", "content": payload.get("content", "")})
            elif t == "ai":
                tool_calls = payload.get("tool_calls") or []
                message = {
                    "role": "assistant",
                    "content": payload.get("content", "") or None,
                }
                if tool_calls:
                    cc = []
                    for i, tc in enumerate(tool_calls):
                        cc.append({
                            "id": tc.get("id") or f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": tc.get("name"),
                                "arguments": json.dumps(tc.get("arguments") or {}),
                            }
                        })
                    message["tool_calls"] = cc
                msgs.append(message)
                invalids = payload.get("invalid_tool_calls") or []
                if invalids:
                    pass
            elif t == "tool":
                msgs.append({
                    "role": "tool",
                    "tool_call_id": payload.get("tool_call_id", ""),
                    "content": payload.get("content", ""),
                })
        except Exception:
            continue
    return msgs[-50:]

# --- Диспетчер инструментов (совместим с твоей логикой) ---

async def dispatch_tool_call(tool_call, image_client, user_id: int, max_photo_generations: int | None = None) -> Any:
    # совместим как раньше: поддержка объекта/словаря
    if hasattr(tool_call, "function"):
        name = tool_call.function.name
        args_raw = tool_call.function.arguments
        call_id = getattr(tool_call, "id", None)
    else:
        name = tool_call.get("function", {}).get("name") or tool_call.get("name")
        args_raw = tool_call.get("function", {}).get("arguments") or tool_call.get("arguments")
        call_id = tool_call.get("id")

    if isinstance(args_raw, dict):
        args = args_raw
    else:
        try:
            args = json.loads(args_raw)
        except Exception:
            first_obj = (args_raw or "").split('}', 1)[0] + '}'
            args = json.loads(first_obj)

    user = await users_repository.get_user_by_user_id(user_id=user_id)
    photo_bytes = []
    if name == "add_notification":
        when_send_str, text_notification = args.get("when_send_str"), args.get("text_notification")
        try:
            await schedule_notification(user_id=user.user_id, when_send_str=when_send_str, text_notification=text_notification)
            return f"✅ Отлично! Уведомление установлено на {when_send_str} по московскому времени\n\n📝 Текст напоминания: {text_notification}"
        except NotificationLimitError:
            active_notifications = await notifications_repository.get_active_notifications_by_user_id(user_id)
            return (f"❌ Превышен лимит уведомлений. У вас уже есть {len(active_notifications)} активных уведомлений. Максимум: 10.")
        except NotificationFormatError:
            return "❌ Неверный формат даты/времени. Используйте ГГГГ-ММ-ДД ЧЧ:ММ:СС"
        except NotificationDateTooFarError:
            return "❌ Дата слишком далекая. Допускается до 2030 года."
        except NotificationDateInPastError:
            return "❌ Указанный год уже прошёл."
        except NotificationPastTimeError:
            return "❌ Время уже прошло. Укажите будущее время."
        except NotificationTextTooShortError:
            return "❌ Текст уведомления слишком короткий (>=3 символов)."
        except NotificationTextTooLongError:
            return "❌ Текст уведомления слишком длинный (<=500 символов)."
        except Exception:
            return "❌ Ошибка при создании уведомления. Попробуйте ещё раз."

    if name == "search_web":
        query = args.get("query") or ""
        return await web_search_agent.search_prompt(query)

    if user.last_image_id is not None:
        for photo_id in user.last_image_id.split(", "):
            main_bot = get_current_bot()
            photo_bytes_io = io.BytesIO()
            try:
                await main_bot.download(photo_id, destination=photo_bytes_io)
                photo_bytes_io.seek(0)
                photo_bytes.append(photo_bytes_io.read())
            except:
                pass

    if name == "generate_image":
        try:
            kwargs: dict[str, Any] = {
                "prompt": args["prompt"],
                "n": args.get("n", 1) if (max_photo_generations and max_photo_generations > args.get("n", 1)) else args.get("n", 1),
                "size": args.get("size", DEFAULT_IMAGE_SIZE),
                "quality": args.get("quality", "low"),
            }
            if args.get("edit_existing_photo"):
                kwargs["images"] = [("image.png", io.BytesIO(photo), "image/png") for photo in photo_bytes]
            return await image_client.generate(**kwargs)
        except:
            return []

    if name == "fitting_clothes":
        fitroom_client = FitroomClient()
        cloth_type = (args.get("cloth_type") or "full").strip()
        swap_photos = args.get("swap_photos") or False
        if len(photo_bytes) != 2:
            return "Дорогой друг, пришли фото человека и фото одежды одним сообщением! Ровно две фотографии!"
        if swap_photos:
            model_bytes = photo_bytes[1]
            cloth_bytes = photo_bytes[0]
        else:
            model_bytes = photo_bytes[0]
            cloth_bytes = photo_bytes[1]
        try:
            main_bot = get_current_bot()
            result_bytes = await fitroom_client.try_on(
                model_bytes=model_bytes,
                cloth_bytes=cloth_bytes,
                cloth_type=cloth_type,
                send_bot=main_bot,
                chat_id=user_id,
                validate=False,
            )
            return [result_bytes]
        except Exception:
            return []
        finally:
            try:
                await fitroom_client.close()
            except:
                pass

    if name == "edit_image_only_with_peoples":
        try:
            prompt = (args.get("prompt") or "").strip()[:400]
            prompt = prompt.encode("ascii", "ignore").decode()
            if not prompt:
                return []
            return [await generate_image_bytes(prompt=args.get("prompt"), ratio=args.get("ratio"),
                                               images=photo_bytes if len(photo_bytes) <= 3 else photo_bytes[:3])]
        except Exception:
            return []

    return None

# --- Выполнение tool-calls в режиме Chat Completions ---

async def run_tools_and_followup_chat(
    client: AsyncOpenAI,
    model: str,
    messages: List[dict],
    tool_calls: List[dict],
    user_id: int,
    max_photo_generations: int,
) -> Tuple[List[bytes], Optional[str], Optional[str], List[dict]]:
    image_client = AsyncOpenAIImageClient()
    outputs_messages: List[dict] = []
    final_images: List[bytes] = []
    web_answer = None
    notif_answer = None
    images_counter = 0

    main_bot = get_current_bot()
    from settings import sub_text
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user.user_id)
    type_sub = await type_subscriptions_repository.get_type_subscription_by_id(type_id=user_sub.type_subscription_id) if user_sub else None
    sub_types = await type_subscriptions_repository.select_all_type_subscriptions()

    delete_message = None
    for tc in tool_calls:
        fname = tc["function"]["name"]
        if user_sub is None or (type_sub is not None and type_sub.plan_name == "Free"):
            if fname not in ("search_web", "add_notification"):
                await main_bot.send_message(chat_id=user.user_id,
                                            text="🚨 Эта функция доступна только по подписке\n\n" + sub_text,
                                            reply_markup=subscriptions_keyboard(sub_types).as_markup())
                raise NoSubscription(f"User {user.user_id} dont has active subscription")

        if fname == "search_web":
            delete_message = await main_bot.send_message(text="🔍Начал поиск в интернете, анализирую страницы...",
                                                         chat_id=user.user_id)
        elif fname == "add_notification":
            delete_message = await main_bot.send_message(text="🖌Начал настраивать напоминание...",
                                                         chat_id=user.user_id)
        else:
            if user_sub.photo_generations <= 0:
                generations_packets = await generations_packets_repository.select_all_generations_packets()
                from settings import buy_generations_text
                if type_sub and type_sub.plan_name == "Free":
                    await main_bot.send_message(chat_id=user.user_id,
                                                text="🚨 Эта функция доступна только по подписке\n\n" + sub_text,
                                                reply_markup=subscriptions_keyboard(sub_types).as_markup())
                    raise NoSubscription(f"User {user.user_id} dont has active subscription")
                await main_bot.send_message(chat_id=user_id, text=buy_generations_text,
                                            reply_markup=more_generations_keyboard(generations_packets).as_markup())
                raise NoGenerations(f"User {user.user_id} dont has generations")
            delete_message = await main_bot.send_message(chat_id=user.user_id,
                                                         text="🎨Начал работу над изображением, немного магии…")
        break

    try:
        for tc in tool_calls:
            fname = tc["function"]["name"]
            tool_id = tc.get("id") or ""
            result = await dispatch_tool_call(tc, image_client, user_id=user_id, max_photo_generations=max_photo_generations)

            if fname == "search_web":
                web_answer = result
                outputs_messages.append({"role": "tool", "tool_call_id": tool_id, "content": json.dumps({"text": web_answer}, ensure_ascii=False)})
                continue

            if fname == "add_notification":
                notif_answer = result
                outputs_messages.append({"role": "tool", "tool_call_id": tool_id, "content": json.dumps({"text": notif_answer}, ensure_ascii=False)})
                continue

            if isinstance(result, str):
                outputs_messages.append({"role": "tool", "tool_call_id": tool_id, "content": json.dumps({"text": result}, ensure_ascii=False)})
                continue

            if result is None:
                outputs_messages.append({"role": "tool", "tool_call_id": tool_id, "content": "ignored"})
                continue

            if isinstance(result, list):
                if images_counter >= max_photo_generations:
                    outputs_messages.append({"role": "tool", "tool_call_id": tool_id, "content": "Лимит генераций исчерпан"})
                    continue
                images_counter += len(result)
                final_images.extend(result)
                file_ids = []
                for idx, img in enumerate(result):
                    # сохраняем как файл в Files API (purpose=vision), чтобы вернуть ids в текст
                    f = await client.files.create(file=(f"result_{idx}.png", io.BytesIO(img), "image/png"), purpose="vision")
                    file_ids.append(f.id)
                outputs_messages.append({"role": "tool", "tool_call_id": tool_id,
                                         "content": json.dumps({"file_ids": file_ids}, ensure_ascii=False)})
            else:
                outputs_messages.append({"role": "tool", "tool_call_id": tool_id, "content": "ok"})
    finally:
        if delete_message:
            try:
                await delete_message.delete()
            except:
                pass

    followup_messages = messages + outputs_messages
    comp2 = await client.chat.completions.create(
        model=model,
        messages=followup_messages,
        temperature=0.7,
    )

    content_text = (comp2.choices[0].message.content or "").strip()
    if notif_answer and "✅" in notif_answer:
        user_notifications = await notifications_repository.get_active_notifications_by_user_id(user_id=user_id)
        # клавиатуру вернём уже в вызывающем коде
    return final_images, web_answer, notif_answer, [comp2.choices[0].message.model_dump()]

# --- Построение контента user-сообщения (текст/изображения/документы/аудио) ---

async def build_user_content_for_chat(
    client: AsyncOpenAI,
    text: str,
    image_bytes: Sequence[io.BytesIO] | None,
    document_bytes: Sequence[tuple[io.BytesIO, str, str]] | None,
    audio_bytes: io.BytesIO | None,
) -> List[dict]:
    # Chat Completions: изображения – через image_url base64, документы – как текстовое перечисление
    photos: List[dict] = []
    content = []
    image_names = []
    if image_bytes:
        for idx, img_io in enumerate(image_bytes):
            img_io.seek(0)
            b = img_io.read()
            image_names.append(f"image_{idx}.png")
            photos.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{_b64(b)}"
                }
            })

    text_final = f"Сегодня - {get_current_datetime_string()} по Москве.\n\n{text or 'Вот информация'}"
    if image_names:
        text_final += f"\n\nВот названия изображений: {', '.join(image_names)}"

    if document_bytes:
        text_final += "\n\nВот названия файлов, которые я прикрепил:\n"
        for idx, (doc_io, file_name, mime_ext) in enumerate(document_bytes):
            doc_io.seek(0)
            doc_file = await client.files.create(
                file=(f"{file_name}", doc_io, f"application/{mime_ext}"),
                purpose="user_data",
            )
            text += f"{file_name} "
            content.append({
                "type": "file",
                "file": {"file_id": doc_file.id, "filename": file_name + "." + mime_ext},

            })
    content.append({"type": "text", "text": text_final})
    # Chat API ожидает строку content либо массив частей с текстом/картинками.
    if photos:
        content.extend(photos)
    return content   # чисто текст

# --- Основной класс: полная замена Assistants→Completions ---

class GPTCompletions:  # noqa: N801
    def __init__(self):
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.history = HistoryStore()

    async def _reset_client(self):
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    async def send_message(
        self,
        user_id: int,
        thread_id: str | None = None,      # игнорируется, оставлено для совместимости
        *,
        with_audio_transcription: bool = False,
        text: str | None = None,
        image_bytes: Sequence[io.BytesIO] | None = None,
        document_bytes: Sequence[tuple[io.BytesIO, str, str]] | None = None,
        document_type: str | None = None,
        audio_bytes: io.BytesIO | None = None,
        user_data: Users | None = None,
    ):
        final_content = {
            "text": None,
            "image_files": [],
            "files": [],
            "audio_file": None,
            "reply_markup": None
        }
        main_bot = get_current_bot()
        from bot import logger
        from settings import get_weekday_russian

        user = await users_repository.get_user_by_user_id(user_id=user_id)
        about_user = user.context

        # 1) грузим историю из БД и строим messages
        stored = await self.history.load(user_id=user_id)
        messages = _map_history_to_chat_messages(stored)

        # 2) system-инструкции (как раньше в run.instructions)
        system_text = (
            "ВАЖНАЯ ИНФОРМАЦИЯ О ВРЕМЕНИ:\n"
            f"Текущие дата и время в Москве: {get_current_datetime_string()}\n"
            f"Сегодня {get_weekday_russian()}\n"
            "ВСЕ уведомления и напоминания должны устанавливаться в московском времени!\n"
            "Примеры относительных дат:\n"
            "- 'завтра' = следующий день после сегодняшнего\n"
            "- 'послезавтра' = через два дня\n"
            "- 'на следующей неделе в понедельник' = ближайший понедельник после текущей недели\n"
            "- 'через 30 минут' = добавить 30 минут к текущему времени\n\n"
        )
        if about_user:
            system_text += f"Информация о пользователе:\n{about_user}\n\n"
        messages = [{"role": "system", "content": system_text}] + messages

        # 3) вход пользователя
        if not any([text, image_bytes, document_bytes, audio_bytes]):
            final_content["text"] = "Не получен контент для обработки"
            return final_content

        content = await build_user_content_for_chat(
            self.client,
            text or "",
            image_bytes=image_bytes,
            document_bytes=document_bytes,
            audio_bytes=audio_bytes,
        )
        messages.append({"role": "user", "content": content})

        # 4) сохранить вход как JSON в БД
        human_json = {
            "type": "human",
            "content": content[0].get("text") if content and isinstance(content[0], dict) else (text or ""),
            "additional_kwargs": {"content_parts": content},  # ← сохраняем весь массив частей
            "response_metadata": {},
        }


        # 5) вызов Chat Completions
        lock = await get_thread_lock(str(user_id))
        async with lock:
            try:
                from settings import tools
                tools_payload = _tools_for_chat_completions(tools or [])
                comp = await self.client.chat.completions.create(
                    model=user.model_type,
                    messages=messages,
                    tools=tools_payload if tools_payload else None,
                    temperature=0.7,
                )
                await self.history.append(user_id=user_id, payload=human_json)
                msg = comp.choices[0].message
                tool_calls = getattr(msg, "tool_calls", None) or msg.model_extra.get("tool_calls") if hasattr(msg, "model_extra") else None

                # 6) если тулзы требуются — выполним и второй запрос
                if tool_calls:
                    # проверки подписок/лимитов внутри run_tools_and_followup_chat
                    user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user.user_id)
                    max_photo_generations = user_sub.photo_generations if user_sub else 0
                    final_images, web_answer, notif_answer, assistant_msgs = await run_tools_and_followup_chat(
                        client=self.client,
                        model=user.model_type,
                        messages=messages + [{"role": "assistant", "content": msg.content or None, "tool_calls": [tc.model_dump() for tc in tool_calls]}],
                        tool_calls=[tc.model_dump() for tc in tool_calls],
                        user_id=user.user_id,
                        max_photo_generations=max_photo_generations,
                    )

                    # выдача пользователю
                    if web_answer:
                        final_text = sanitize_with_links(web_answer)
                        ai_json = {
                            "type": "ai",
                            "content": final_text,
                            "tool_calls": [],
                            "additional_kwargs": {},
                            "response_metadata": {},
                            "invalid_tool_calls": [],
                        }
                        await self.history.append(user_id=user_id, payload=ai_json)
                        final_content["text"] = final_text
                        return final_content

                    if notif_answer:
                        final_text = sanitize_with_links(notif_answer)
                        ai_json = {
                            "type": "ai",
                            "content": final_text,
                            "tool_calls": [],
                            "additional_kwargs": {},
                            "response_metadata": {},
                            "invalid_tool_calls": [],
                        }
                        await self.history.append(user_id=user_id, payload=ai_json)
                        final_content["text"] = final_text
                        if "✅" in final_text:
                            user_notifications = await notifications_repository.get_active_notifications_by_user_id(user_id=user_id)
                            final_content["reply_markup"] = delete_notification_keyboard(user_notifications[-1].id)
                        return final_content

                    if final_images:
                        # Списание генераций
                        if user_sub:
                            await subscriptions_repository.use_generation(subscription_id=user_sub.id, count=len(final_images))
                        # Текст из второго ответа
                        assistant_text = assistant_msgs[0].get("content") or "Сгенерировал изображение"
                        final_text = sanitize_with_links(assistant_text)
                        ai_json = {
                            "type": "ai",
                            "content": final_text,
                            "tool_calls": [],
                            "additional_kwargs": {},
                            "response_metadata": {},
                            "invalid_tool_calls": [],
                        }
                        await self.history.append(user_id=user_id, payload=ai_json)
                        final_content["text"] = final_text
                        final_content["image_files"] = final_images
                        return final_content

                    # если тулзы отработали, но ничего не вернули ощутимого
                    final_text = (assistant_msgs[0].get("content") or "").strip() or "Не удалось обработать запрос."
                    final_text = sanitize_with_links(final_text)
                    ai_json = {
                        "type": "ai",
                        "content": final_text,
                        "tool_calls": [],
                        "additional_kwargs": {},
                        "response_metadata": {},
                        "invalid_tool_calls": [],
                    }
                    await self.history.append(user_id=user_id, payload=ai_json)
                    final_content["text"] = final_text
                    return final_content

                # 7) обычный ответ ассистента без тулзов
                message_text = msg.content or ""
                if with_audio_transcription:
                    audio_data = await tts_generate_audio_mp3(message_text)
                    final_text = sanitize_with_links(message_text)
                    ai_json = {
                        "type": "ai",
                        "content": final_text,
                        "tool_calls": [],
                        "additional_kwargs": {},
                        "response_metadata": {},
                        "invalid_tool_calls": [],
                    }
                    await self.history.append(user_id=user_id, payload=ai_json)
                    final_content["text"] = final_text
                    final_content["audio_file"] = audio_data
                    return final_content

                final_text = sanitize_with_links(message_text)
                ai_json = {
                    "type": "ai",
                    "content": final_text,
                    "tool_calls": [],
                    "additional_kwargs": {},
                    "response_metadata": {},
                    "invalid_tool_calls": [],
                }
                await self.history.append(user_id=user_id, payload=ai_json)
                final_content["text"] = final_text
                return final_content

            except NoSubscription:
                raise
            except NoGenerations:
                raise
            except Exception:
                await self._reset_client()
                logger.log("GPT_ERROR", f"{user_id} | Ошибка в ответе gpt: {traceback.format_exc()}")
                print_log(message=f"{user_id} | Ошибка в ответе gpt: {traceback.format_exc()}")
                final_content["text"] = ("Произошла непредвиденная ошибка, попробуй еще раз! "
                                         "Твой запрос может содержать контент, который не разрешен нашей системой безопасности")
                return final_content

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
