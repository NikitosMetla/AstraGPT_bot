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

from settings import get_current_datetime_string, print_log, get_current_bot, gemini_images_client
from data.keyboards import subscriptions_keyboard, more_generations_keyboard, delete_notification_keyboard, \
    more_video_generations_keyboard
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
from utils.google_banano_generate import ResponseBlockedError, PromptBlockedError, TextRefusalError, \
    NoImageInResponseError, InvalidPromptError, AuthError, TransientError, GeminiImageError, RateLimitError
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
    notifications_repository, dialogs_messages_repository, video_generations_packets_repository,
)
from db.models import DialogsMessages

# --- глобальные переменные и инициализация ---

load_dotenv(find_dotenv())
NEURO_GPT_TOKEN: str | None = os.getenv("NEURO_GPT_TOKEN")
OPENAI_API_KEY: str | None = os.getenv("GPT_TOKEN")
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
        "Authorization": f"Bearer {NEURO_GPT_TOKEN}",
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
                        fn = (tc.get("function") or {})
                        name = fn.get("name") or ""  # Должна быть непустая строка
                        args = fn.get("arguments")
                        # OpenAI ждёт СТРОКУ в arguments. Если вдруг словарь — превратим в строку.
                        if isinstance(args, dict):
                            args = json.dumps(args, ensure_ascii=False)
                        if not isinstance(args, str) or not args:
                            args = "{}"
                        cc.append({
                            "id": tc.get("id") or f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": args,
                            }
                        })
                    message["tool_calls"] = cc
                msgs.append(message)
            elif t == "tool":
                msgs.append({
                    "role": "tool",
                    "tool_call_id": payload.get("tool_call_id", ""),
                    "content": payload.get("content", ""),
                })
        except Exception:
            continue
    return msgs[-50:]


def _sanitize_messages_for_chat_api(msgs: List[dict]) -> List[dict]:
    """
    Делает историю валидной для Chat Completions:
    - убирает ведущие 'tool'
    - пропускает 'tool', если перед ним нет ассистента с нужным tool_call_id
    - если ассистент с tool_calls не получил все ответы tool подряд — выкидываем этого ассистента и связанные tool
    """
    if not msgs:
        return msgs

    # 1) срезаем все ведущие 'tool'
    i = 0
    while i < len(msgs) and msgs[i].get("role") == "tool":
        i += 1
    msgs = msgs[i:]

    out: List[dict] = []
    pending: set[str] = set()   # набор tool_call_id, которые мы еще ждём
    collecting_tools_for_last_assistant = False
    buffer_tools: List[dict] = []

    for m in msgs:
        role = m.get("role")
        if role == "assistant":
            # если у предыдущего ассистента оставались незакрытые tool_calls,
            # выкидываем его и буфер tool-ов
            if pending:
                if out and out[-1].get("role") == "assistant":
                    out.pop()
                buffer_tools.clear()
                pending.clear()

            out.append(m)
            tc = m.get("tool_calls") or []
            pending = {tc_i.get("id") for tc_i in tc if tc_i.get("id")}
            collecting_tools_for_last_assistant = bool(pending)
            buffer_tools.clear()

        elif role == "tool":
            tcid = m.get("tool_call_id")
            # учитываем tool только если прямо перед этим был ассистент с таким id
            if collecting_tools_for_last_assistant and tcid in pending and out and out[-1].get("role") == "assistant":
                buffer_tools.append(m)
                pending.discard(tcid)
                # когда всё закрыли — фиксируем буфер в out
                if not pending:
                    out.extend(buffer_tools)
                    buffer_tools.clear()
                    collecting_tools_for_last_assistant = False
            else:
                # осиротевший tool — просто пропускаем
                continue

        else:
            # пришёл user/system и т.п.
            # если ассистент выше ждал ещё tool — выкидываем того ассистента и буфер
            if pending:
                if out and out[-1].get("role") == "assistant":
                    out.pop()
                buffer_tools.clear()
                pending.clear()
                collecting_tools_for_last_assistant = False
            out.append(m)

    # хвост: если диалог закончился на ассистенте с незакрытыми tool_calls — выкидываем его
    if pending and out and out[-1].get("role") == "assistant":
        out.pop()

    return out


# --- Диспетчер инструментов (совместим с твоей логикой) ---

def _norm_args(args_raw: str | dict) -> str:
    if isinstance(args_raw, dict):
        return json.dumps(args_raw, ensure_ascii=False, sort_keys=True)
    try:
        obj = json.loads(args_raw or "{}")
        return json.dumps(obj, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(args_raw)

def _dedup_tool_calls(tool_calls: List[dict]) -> List[dict]:
    seen: dict[tuple[str, str], dict] = {}
    def _norm_args(args_raw: str | dict) -> str:
        if isinstance(args_raw, dict):
            return json.dumps(args_raw, ensure_ascii=False, sort_keys=True)
        try:
            obj = json.loads(args_raw or "{}")
            return json.dumps(obj, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(args_raw)
    out: List[dict] = []
    for tc in tool_calls:
        f = tc.get("function") or {}
        key = (f.get("name") or "", _norm_args(f.get("arguments")))
        if key in seen:
            continue
        seen[key] = tc
        out.append(tc)
    return out



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
    # print(name)
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

    # if name == "generate_image":
    #     try:
    #         kwargs: dict[str, Any] = {
    #             "prompt": args["prompt"],
    #             "n": args.get("n", 1) if (max_photo_generations and max_photo_generations > args.get("n", 1)) else args.get("n", 1),
    #             "size": args.get("size", DEFAULT_IMAGE_SIZE),
    #             "quality": args.get("quality", "low"),
    #         }
    #         if args.get("edit_existing_photo"):
    #             kwargs["images"] = [("image.png", io.BytesIO(photo), "image/png") for photo in photo_bytes]
    #         return await image_client.generate(**kwargs)
    #     except:
    #         return []
    error_text = """Прости, но я не смогла сгенерировать изображение 😞

Попробуй еще раз, переформулировав запрос и в очистив контекст диалога c помощью команды /clear_context *☘️

Если ошибка возникает на постоянной основе, можешь обратиться в @sozdav_ai, наши специалисты помогут тебе разобраться! 🤗

*Убедитесь, что вы избегаете нецензурных тем и насилия ❌"""
    if name == "generate_gemini_image":
        from settings import logger
        try:
            kwargs: dict[str, Any] = {
                "prompt": args["prompt"],
            }
            print(args["prompt"])
            if args.get("with_photo_references", False):
                kwargs["reference_images"] = [io.BytesIO(photo).read() for photo in photo_bytes]
            result = await gemini_images_client.generate_gemini_image(**kwargs)
            return [result]

        except PromptBlockedError as e:
#             error_text = """Мы не можем выполнить запрос из-за ограничений безопасности.
# Попробуйте переформулировать: без упоминания конкретных публичных персон и в нереалистичном стиле (например, «cartoon/illustration»), либо заменить «рядом с X» на «на фоне постера/силуэта»."""
            logger.log("GPT_ERROR", error_text + "\n\n" + traceback.format_exc())
            return error_text

        except ResponseBlockedError as e:
#             error_text = """Генерация остановлена правилами безопасности модели.
# Измените запрос: уберите имя публичной персоны, выберите нереалистичный стиль (cartoon/illustration), используйте «постер/баннер/силуэт» вместо фотореалистичного совместного фото."""
            logger.log("GPT_ERROR", error_text + "\n\n" + traceback.format_exc())
            return error_text

        except TextRefusalError as e:
#             error_text = """Модель отказалась выполнить запрос, так как он нарушает правила или содержит элементы, которые не могут быть корректно обработаны. Это может происходить, если описание противоречит изображению, затрагивает чувствительные темы или содержит недопустимые элементы.
# Рекомендация: попробуйте упростить запрос, убрать имена публичных персон и выбрать нереалистичный стиль (например, cartoon/illustration)."""
            logger.log("GPT_ERROR", error_text + "\n\n" + traceback.format_exc())
            return error_text

        except NoImageInResponseError as e:
#             error_text = """По текущему запросу изображение не сформировано.
# Попробуйте упростить описание и убрать потенциально чувствительные элементы (имена, фотореалистичность), либо выбрать стиль «иллюстрация»."""
            logger.log("GPT_ERROR", error_text + "\n\n" + traceback.format_exc())
            return error_text

        except InvalidPromptError as e:
            error_text = """Нужен текстовый запрос. Опишите сцену в 1-2 предложениях: кто/что, стиль (cartoon/illustration), фон."""
            logger.log("GPT_ERROR", error_text + "\n\n" + traceback.format_exc())
            return error_text

        except AuthError as e:
            error_text = ("В связи с большим наплывом пользователей"
                         " наши сервера испытывают экстремальные нагрузки."
                         " Скоро генерация изображений станет снова доступна,"
                         " а пока можете воспользоваться другим функционалом."
                         " Я умею немало 🤗")
            logger.log("GPT_ERROR", error_text + "\n\n" + traceback.format_exc())
            return error_text

        except RateLimitError as e:
            error_text = ("В связи с большим наплывом пользователей"
                          " наши сервера испытывают экстремальные нагрузки."
                          " Скоро генерация изображений станет снова доступна,"
                          " а пока можете воспользоваться другим функционалом."
                          " Я умею немало 🤗")
            logger.log("GPT_ERROR", error_text + "\n\n" + traceback.format_exc())
            return error_text

        except TransientError as e:
            error_text = ("В связи с большим наплывом пользователей"
                          " наши сервера испытывают экстремальные нагрузки."
                          " Скоро генерация изображений станет снова доступна,"
                          " а пока можете воспользоваться другим функционалом."
                          " Я умею немало 🤗")
            logger.log("GPT_ERROR", error_text + "\n\n" + traceback.format_exc())
            return error_text

        except GeminiImageError as e:
            error_text = ("В связи с большим наплывом пользователей"
                          " наши сервера испытывают экстремальные нагрузки."
                          " Скоро генерация изображений станет снова доступна,"
                          " а пока можете воспользоваться другим функционалом."
                          " Я умею немало 🤗")
            logger.log("GPT_ERROR", error_text + "\n\n" + traceback.format_exc())
            return error_text

        except Exception as e:
            logger.log("GPT_ERROR", traceback.format_exc())
            return []

    from settings import _split_ids, build_telegram_image_urls_from_ids
    image_urls: list[str] = []
    if user.last_image_id:
        bot = get_current_bot()
        image_ids = _split_ids(user.last_image_id)
        image_urls = await build_telegram_image_urls_from_ids(bot, image_ids)

    if name == "generate_text_to_video":
        from settings import logger, sora_client
        from utils.sora_client import (
            InsufficientCreditsError,
            ContentPolicyError,
            RateLimitError,
            KieSora2Error
        )

        try:
            kwargs: dict[str, Any] = {
                "prompt": args["prompt"],
                "aspect_ratio": args.get("aspect_ratio", "landscape"),
                "quality": args.get("quality", "standard"),
            }

            logger.info(f"Запуск генерации видео: {args['prompt'][:100]}...")
            result = await sora_client.text_to_video(**kwargs)
            logger.info(f"Видео готово: {result}")
            return result

        except InsufficientCreditsError as e:
            logger.log("Sora2Error",f"Недостаточно кредитов: {e}")
            return ("В связи с большим наплывом пользователей"
                     " наши сервера испытывают экстремальные нагрузки."
                     " Скоро генерация изображений станет снова доступна,"
                     " а пока можете воспользоваться другим функционалом."
                     " Я умею немало 🤗")

        except ContentPolicyError as e:
            logger.log("Sora2Error",f"Нарушение content policy: {e}")
            return "Ваш запрос был отклонён системой безопасности. Пожалуйста, измените описание видео, убрав упоминания конкретных людей, знаменитостей или потенциально небезопасный контент, и попробуйте снова."

        except RateLimitError as e:
            logger.log("Sora2Error",f"Rate limit превышен: {e}")
            return "Слишком много запросов на генерацию видео. Пожалуйста, подождите 1-2 минуты и попробуйте снова."

        except asyncio.TimeoutError:
            logger.log("Sora2Error","Таймаут генерации видео")
            return "Генерация видео заняла слишком много времени (более 15 минут) и была прервана. Попробуйте упростить описание или выбрать качество 'standard' вместо 'hd'."

        except KieSora2Error as e:
            error_msg = str(e)
            logger.log("Sora2Error", f"Ошибка Sora API: {error_msg}")

            if "Эндпоинт не найден" in error_msg:
                return "Сервис временно недоступен, попробуйте позже."
            elif "Ошибка генерации" in error_msg:
                return "Дорогой друг. На данный момент модель не может генерировать видео знаменитостей, а также непристойный контент. Если ты считаешь, что проблема в другом, то обратись в поддержку /support"
            elif "Неверный API ключ" in error_msg:
                return "Ошибка аутентификации с сервисом генерации видео. Пожалуйста, свяжитесь с администратором."
            elif "Ошибка валидации" in error_msg:
                return "Некорректные параметры запроса. Убедитесь, что описание видео не превышает 5000 символов."
            elif "Сервис недоступен" in error_msg or "maintenance" in error_msg.lower():
                return "Сервис генерации видео временно недоступен из-за технического обслуживания. Пожалуйста, попробуйте через 10-15 минут."
            else:
                return f"Не удалось сгенерировать видео: {error_msg}. Попробуйте изменить описание или повторить попытку позже."

        except Exception as e:
            logger.error(f"Неожиданная ошибка при генерации видео: {traceback.format_exc()}")
            return "Произошла непредвиденная ошибка при генерации видео. Пожалуйста, попробуйте ещё раз через несколько минут или обратитесь в поддержку."


    elif name == "generate_image_to_video":
        from settings import logger, sora_client
        from utils.sora_client import (
            InsufficientCreditsError,
            ContentPolicyError,
            RateLimitError,
            KieSora2Error
        )

        try:
            if not args.get("image_provided"):
                return "Для генерации видео из изображения необходимо прикрепить фото. Пожалуйста, отправьте изображение и повторите запрос."

            # Здесь получаешь image_bytes из контекста
            # image_bytes = await get_image_bytes_from_message(message)

            kwargs: dict[str, Any] = {
                "image": image_urls[0],
                "prompt": args["prompt"],
                "aspect_ratio": args.get("aspect_ratio", "landscape"),
                "quality": args.get("quality", "standard"),
            }

            logger.info(f"Запуск генерации видео из изображения: {args['prompt'][:100]}...")
            result = await sora_client.image_to_video(**kwargs)
            logger.info(f"Видео готово: {result}")
            return result

        except InsufficientCreditsError as e:
            logger.log("Sora2Error",f"Недостаточно кредитов: {e}")
            return ("В связи с большим наплывом пользователей"
                    " наши сервера испытывают экстремальные нагрузки."
                    " Скоро генерация изображений станет снова доступна,"
                    " а пока можете воспользоваться другим функционалом."
                    " Я умею немало 🤗")

        except ContentPolicyError as e:
            logger.log("Sora2Error",f"Нарушение content policy: {e}")
            return "Ваше изображение или запрос были отклонены системой безопасности. Убедитесь, что на фото нет узнаваемых лиц знаменитостей или несовершеннолетних, и описание не содержит небезопасный контент."

        except RateLimitError as e:
            logger.log("Sora2Error",f"Rate limit превышен: {e}")
            return "Слишком много запросов на генерацию видео. Пожалуйста, подождите 1-2 минуты и попробуйте снова."

        except asyncio.TimeoutError:
            logger.log("Sora2Error","Таймаут генерации видео")
            return "Генерация видео заняла слишком много времени (более 15 минут) и была прервана. Попробуйте упростить описание анимации или выбрать качество 'standard' вместо 'hd'."

        except KieSora2Error as e:
            error_msg = str(e)
            logger.log("Sora2Error",f"Ошибка Sora API: {error_msg}")

            if "Файл не найден" in error_msg:
                return "Не удалось получить доступ к изображению. Пожалуйста, отправьте изображение заново."
            elif "Ошибка генерации" in error_msg:
                return "Дорогой друг. На данный момент модель не может генерировать видео на основе фото живых людей, знаменитостей, а также непристойный контент. Если ты считаешь, что проблема в другом, то обратись в поддержку /support"
            elif "image должен быть" in error_msg:
                return "Некорректный формат изображения. Пожалуйста, отправьте изображение в формате JPEG, PNG или WEBP размером до 10 МБ."
            elif "Эндпоинт не найден" in error_msg:
                return "Сервис временно недоступен, попробуйте позже."
            elif "Неверный API ключ" in error_msg:
                return "Ошибка аутентификации с сервисом генерации видео. Пожалуйста, свяжитесь с администратором."
            elif "Сервис недоступен" in error_msg or "maintenance" in error_msg.lower():
                return "Сервис генерации видео временно недоступен из-за технического обслуживания. Пожалуйста, попробуйте через 10-15 минут."
            else:
                return f"Не удалось сгенерировать видео из изображения: {error_msg}. Попробуйте другое изображение или повторите попытку позже."

        except Exception as e:
            logger.log("Sora2Error",f"Неожиданная ошибка при генерации видео из изображения: {traceback.format_exc()}")
            return "Произошла непредвиденная ошибка при генерации видео. Пожалуйста, попробуйте ещё раз через несколько минут или обратитесь в поддержку /support."


    # if name == "fitting_clothes":
    #     fitroom_client = FitroomClient()
    #     cloth_type = (args.get("cloth_type") or "full").strip()
    #     swap_photos = args.get("swap_photos") or False
    #     if len(photo_bytes) != 2:
    #         return "Дорогой друг, пришли фото человека и фото одежды одним сообщением! Ровно две фотографии!"
    #     if swap_photos:
    #         model_bytes = photo_bytes[1]
    #         cloth_bytes = photo_bytes[0]
    #     else:
    #         model_bytes = photo_bytes[0]
    #         cloth_bytes = photo_bytes[1]
    #     try:
    #         main_bot = get_current_bot()
    #         result_bytes = await fitroom_client.try_on(
    #             model_bytes=model_bytes,
    #             cloth_bytes=cloth_bytes,
    #             cloth_type=cloth_type,
    #             send_bot=main_bot,
    #             chat_id=user_id,
    #             validate=False,
    #         )
    #         return [result_bytes]
    #     except Exception:
    #         return []
    #     finally:
    #         try:
    #             await fitroom_client.close()
    #         except:
    #             pass
    #
    # if name == "edit_image_only_with_peoples":
    #     try:
    #         prompt = (args.get("prompt") or "").strip()[:400]
    #         prompt = prompt.encode("ascii", "ignore").decode()
    #         if not prompt:
    #             return []
    #         return [await generate_image_bytes(prompt=args.get("prompt"), ratio=args.get("ratio"),
    #                                            images=photo_bytes if len(photo_bytes) <= 3 else photo_bytes[:3])]
    #     except Exception:
    #         return []

    return None

# --- Выполнение tool-calls в режиме Chat Completions ---

async def _append_tool_message(
    user_id: int,
    tool_call_id: str,
    name: str,
    content_obj: dict | str,
    outputs_messages: list[dict],
):
    """Единообразно:
    1) добавляем role=tool в массив outputs_messages (для второго шага модели),
    2) сохраняем 'type=tool' в БД для последующих запросов.
    """
    if isinstance(content_obj, dict):
        content_str = json.dumps(content_obj, ensure_ascii=False)
    else:
        content_str = str(content_obj)

    tool_payload = {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": content_str,
    }
    outputs_messages.append(tool_payload)

    tool_db_json = {
        "type": "tool",
        "tool_call_id": tool_call_id,
        "name": name,
        "content": content_str,
    }
    await dialogs_messages_repository.add_message(user_id=user_id, message=tool_db_json)


async def run_tools_and_followup_chat(
    client: AsyncOpenAI,
    model: str,
    messages: List[dict],
    tool_calls: List[dict],
    user_id: int,
    max_photo_generations: int,
) -> Tuple[List[bytes], Optional[str], Optional[str], List[dict], List[str]]:
    image_client = AsyncOpenAIImageClient()
    outputs_messages: List[dict] = []
    final_images: List[bytes] = []
    video_urls: List[str] = []
    web_answer: Optional[str] = None
    notif_answer: Optional[str] = None
    images_counter = 0

    # Дедуп по (имя, нормализованные аргументы)
    tool_calls = _dedup_tool_calls(tool_calls)

    main_bot = get_current_bot()
    from settings import sub_text
    user = await users_repository.get_user_by_user_id(user_id=user_id)
    user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user.user_id)
    type_sub = await type_subscriptions_repository.get_type_subscription_by_id(
        type_id=user_sub.type_subscription_id
    ) if user_sub else None
    sub_types = await type_subscriptions_repository.select_all_type_subscriptions()

    delete_message = None
    stop_event = None
    task = None
    try:
        # Каждый tool_call исполняем ровно один раз
        for tc in tool_calls:
            fname = tc["function"]["name"]
            tool_id = tc.get("id") or ""
            # Проверки подписки/лимитов и индикаторы
            if fname not in ("search_web", "add_notification"):
                if user_sub is None or (type_sub is not None and type_sub.plan_name == "Free"):
                    if user_sub is None:
                        await subscriptions_repository.add_subscription(type_sub_id=2, user_id=user_id,
                                                                        photo_generations=0, time_limit_subscription=30,
                                                                        is_paid_sub=False,
                                                                        video_generations=0)
                        user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user_id)
                    await main_bot.send_message(
                        chat_id=user.user_id,
                        text="🚨 Эта функция доступна только по подписке\n\n" + sub_text,
                        reply_markup=subscriptions_keyboard(sub_types).as_markup(),
                    )
                    # ДОБАВЬ ЭТО: отдаем tool-ответ, чтобы закрыть tool_call
                    await _append_tool_message(
                        user_id=user.user_id,
                        tool_call_id=tool_id,
                        name=fname,
                        content_obj={"error": "forbidden", "reason": "no_subscription"},
                        outputs_messages=outputs_messages,
                    )
                    raise NoSubscription(f"User {user.user_id} dont has active subscription")
                if fname in ("generate_text_to_video", "generate_image_to_video"):
                    if user_sub.video_generations <= 0:
                        from settings import buy_video_generations_text
                        video_generations_packets = await video_generations_packets_repository.select_all_video_generations_packets()
                        if type_sub is not None and type_sub.plan_name == "Free":
                            await main_bot.send_message(
                                chat_id=user.user_id,
                                text="🚨 Эта функция доступна только по подписке\n\n" + sub_text,
                                reply_markup=subscriptions_keyboard(sub_types).as_markup(),
                            )
                            # ДОБАВЬ ЭТО:
                            await _append_tool_message(
                                user_id=user.user_id,
                                tool_call_id=tool_id,
                                name=fname,
                                content_obj={"error": "forbidden", "reason": "no_subscription"},
                                outputs_messages=outputs_messages,
                            )
                            raise NoSubscription(f"User {user.user_id} dont has active subscription")
                        await main_bot.send_message(
                            chat_id=user_id,
                            text=buy_video_generations_text,
                            reply_markup=more_video_generations_keyboard(video_generations_packets).as_markup(),
                        )
                        # ДОБАВЬ ЭТО:
                        await _append_tool_message(
                            user_id=user.user_id,
                            tool_call_id=tool_id,
                            name=fname,
                            content_obj={"error": "quota_exceeded", "reason": "no_video_generations_left"},
                            outputs_messages=outputs_messages,
                        )
                        raise NoGenerations(f"User {user.user_id} dont has generations")
                    from settings import send_initial
                    delete_message = await send_initial(main_bot, user_id)
                else:
                    if user_sub.photo_generations <= 0:
                        generations_packets = await generations_packets_repository.select_all_generations_packets()
                        from settings import buy_generations_text
                        if type_sub is not None and type_sub.plan_name == "Free":
                            await main_bot.send_message(
                                chat_id=user.user_id,
                                text="🚨 Эта функция доступна только по подписке\n\n" + sub_text,
                                reply_markup=subscriptions_keyboard(sub_types).as_markup(),
                            )
                            # ДОБАВЬ ЭТО:
                            await _append_tool_message(
                                user_id=user.user_id,
                                tool_call_id=tool_id,
                                name=fname,
                                content_obj={"error": "forbidden", "reason": "no_subscription"},
                                outputs_messages=outputs_messages,
                            )
                            raise NoSubscription(f"User {user.user_id} dont has active subscription")

                        await main_bot.send_message(
                            chat_id=user_id,
                            text=buy_generations_text,
                            reply_markup=more_generations_keyboard(generations_packets).as_markup(),
                        )
                        # ДОБАВЬ ЭТО:
                        await _append_tool_message(
                            user_id=user.user_id,
                            tool_call_id=tool_id,
                            name=fname,
                            content_obj={"error": "quota_exceeded", "reason": "no_generations_left"},
                            outputs_messages=outputs_messages,
                        )
                        raise NoGenerations(f"User {user.user_id} dont has generations")

                    delete_message = await main_bot.send_message(
                        chat_id=user.user_id,
                        text="🎨Начал работу над изображением, немного магии…",
                    )
            else:
                if fname == "search_web":
                    delete_message = await main_bot.send_message(
                        text="🔍Начал поиск в интернете, анализирую страницы...",
                        chat_id=user.user_id,
                    )
                elif fname == "add_notification":
                    delete_message = await main_bot.send_message(
                        text="🖌Начал настраивать напоминание...",
                        chat_id=user.user_id,
                    )

            # Исполняем инструмент
            result = await dispatch_tool_call(
                tc, image_client, user_id=user_id, max_photo_generations=max_photo_generations
            )

            # Возвращаем ответ инструмента МОДЕЛИ: role="tool" + тот же tool_call_id
            if fname == "search_web":
                web_answer = result or ""
                await _append_tool_message(
                    user_id=user_id,
                    tool_call_id=tool_id,
                    name=fname,
                    content_obj={"text": web_answer},
                    outputs_messages=outputs_messages,
                )
                # --- КОНЕЦ ДОБАВЛЕНИЯ
                continue

            if fname == "add_notification":
                notif_answer = result or ""
                await _append_tool_message(
                    user_id=user_id,
                    tool_call_id=tool_id,
                    name=fname,
                    content_obj={"text": notif_answer},
                    outputs_messages=outputs_messages,
                )
                continue

            if fname in ["generate_text_to_video", "generate_image_to_video"] and isinstance(result, list):
                await _append_tool_message(
                    user_id=user_id,
                    tool_call_id=tool_id,
                    name=fname,
                    content_obj={"text": f"Generated video url: {result[0]}"},
                    outputs_messages=outputs_messages,
                )
                video_urls.extend(result)
                continue

            if fname in ["generate_text_to_video", "generate_image_to_video"] and isinstance(result, str):
                await _append_tool_message(
                    user_id=user_id,
                    tool_call_id=tool_id,
                    name=fname,
                    content_obj=result,
                    outputs_messages=outputs_messages,
                )
                continue

            if isinstance(result, str):
                await _append_tool_message(
                    user_id=user_id,
                    tool_call_id=tool_id,
                    name=fname,
                    content_obj=result,
                    outputs_messages=outputs_messages,
                )
                continue

            if result is None:
                await _append_tool_message(
                    user_id=user_id,
                    tool_call_id=tool_id,
                    name=fname,
                    content_obj={"status": "no_result"},
                    outputs_messages=outputs_messages,
                )
                continue

            if isinstance(result, list):
                if images_counter >= max_photo_generations:
                    await _append_tool_message(
                        user_id=user_id,
                        tool_call_id=tool_id,
                        name=fname,
                        content_obj={"error": "generation_limit"},
                        outputs_messages=outputs_messages,
                    )
                    continue

                images_counter += len(result)
                final_images.extend(result)

                await _append_tool_message(
                    user_id=user_id,
                    tool_call_id=tool_id,
                    name=fname,
                    content_obj={"photo_names": ", ".join([f"image_{idx + 1}.png" for idx in range(len(final_images))])},
                    outputs_messages=outputs_messages,
                )
                continue

            # safety-фоллбек
            await _append_tool_message(
                user_id=user_id,
                tool_call_id=tool_id,
                name=fname,
                content_obj={"status": "ok"},
                outputs_messages=outputs_messages,
            )
    except NoSubscription:
        raise
    except NoGenerations:
        raise
    except Exception:
        from settings import logger
        logger.log("GPT_ERROR", traceback.format_exc())
    finally:
        if stop_event:
            stop_event.set()
        if task:
            await task
        if delete_message:
            try:
                await delete_message.delete()
            except:
                pass

    # Начало вставки
    def _filter_outputs_with_valid_tool_calls(messages: List[dict], outputs_messages: List[dict]) -> List[dict]:
        valid_tool_call_ids = set()
        for m in reversed(messages):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    if 'id' in tc:
                        valid_tool_call_ids.add(tc['id'])
                break

        filtered = []
        for m in outputs_messages:
            if m.get("role") == "tool":
                if m.get("tool_call_id") in valid_tool_call_ids:
                    filtered.append(m)
                else:
                    continue
            else:
                filtered.append(m)
        return filtered

    outputs_messages = _filter_outputs_with_valid_tool_calls(messages, outputs_messages)
    # Конец вставки

    return final_images, web_answer, notif_answer, outputs_messages, video_urls

    # ВТОРОЙ вызов: финализируем ответ МОДЕЛИ
    # followup_messages = messages + outputs_messages
    #
    # # ВАЖНО: tool_choice допустим только вместе с tools.
    # # Берём те же tools, что и в первом вызове. Если их нет — tool_choice не передаём.
    # from settings import tools as _tools_from_settings
    # tools_payload = _tools_for_chat_completions(_tools_from_settings or [])
    # #
    # # if tools_payload:
    # #     comp2 = await client.chat.completions.create(
    # #         model=model,
    # #         messages=followup_messages,
    # #         temperature=0.7,
    # #         tools=tools_payload,     # обязателен, чтобы использовать tool_choice
    # #         tool_choice="none",      # запрещаем новые tool-вызовы
    # #     )
    # # else:
    # #     comp2 = await client.chat.completions.create(
    # #         model=model,
    # #         messages=followup_messages,
    # #         temperature=0.7,
    # #     )
    #
    # # content_text = (comp2.choices[0].message.content or "").strip()
    # if notif_answer and "✅" in notif_answer:
    #     _ = await notifications_repository.get_active_notifications_by_user_id(user_id=user_id)
    #
    # return final_images, web_answer, notif_answer, [comp2.choices[0].message.model_dump()]



# --- Построение контента user-сообщения (текст/изображения/документы/аудио) ---


def _lighten_parts_for_storage(parts: list[dict]) -> list[dict]:
    light = []
    for p in parts or []:
        t = p.get("type")
        if t == "image_url":
            url = (p.get("image_url") or {}).get("url", "")
            # Если это data URL → режем
            if isinstance(url, str) and url.startswith("data:image"):
                light.append({"type": "text", "text": "[image omitted]"})
            else:
                # Оставляем ТОЛЬКО если это нормальный HTTPS-URL
                if isinstance(url, str) and url.startswith("http"):
                    light.append({"type": "image_url", "image_url": {"url": url}})
                else:
                    light.append({"type": "text", "text": "[image omitted]"})
        elif t == "file":
            # В Chat Completions это не используется; в истории сохраняем безопасный маркер
            fname = ((p.get("file") or {}).get("filename")) or "file"
            light.append({"type": "text", "text": f"[file: {fname}]"})
        else:
            # Текст — как есть
            light.append(p)
    return light


def to_b64(data: bytes) -> str:
    """Конвертирует байты в base64 строку"""
    return base64.b64encode(data).decode('utf-8')


async def build_user_content_for_chat(
    client: AsyncOpenAI,
    text: str,
    image_bytes: Sequence[io.BytesIO] | None,
    document_bytes: Sequence[tuple[io.BytesIO, str, str]] | None,
    audio_bytes: io.BytesIO | None,
) -> List[dict]:
    photos: List[dict] = []
    content = []
    image_names = []
    image_names: List[str] = []

    MAX_TEXT_TOKENS_PER_FILE = 10000
    TOTAL_TOKEN_BUDGET = 100000
    total_tokens_used = 0

    def estimate_tokens(text: str) -> int:
        return len(text) // 3

    def truncate_to_tokens(text: str, max_tokens: int) -> str:
        if estimate_tokens(text) <= max_tokens:
            return text

        max_chars = max_tokens * 3
        truncated = text[:max_chars]

        last_newline = truncated.rfind('\n')
        if last_newline > max_chars * 0.8:
            truncated = truncated[:last_newline]

        return truncated

    if image_bytes:
        for idx, img_io in enumerate(image_bytes):
            try:
                img_io.seek(0)
                img_data = img_io.read()
                base64_image = base64.b64encode(img_data).decode('utf-8')

                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{base64_image}"
                    }
                })

                image_names.append(f"image_{idx}.png")

            except Exception as e:
                print(f"[ERROR] Failed to process image {idx}: {e}")
                continue

    text_final = f"Сегодня - {get_current_datetime_string()} по Москве.\n\n{text or 'Вот информация'}"
    if image_names:
        text_final += f"\n\nВот названия изображений: {', '.join(image_names)}"

    if document_bytes:
        for doc_io, file_name, ext in document_bytes:
            raw = doc_io.getvalue()
            ext_l = (ext or "").lower().lstrip(".")
            from settings import SUPPORTED_TEXT_FILE_TYPES

            if ext_l in SUPPORTED_TEXT_FILE_TYPES:
                if total_tokens_used >= TOTAL_TOKEN_BUDGET:
                    break

                try:
                    txt = raw.decode("utf-8", "replace")
                except Exception:
                    txt = raw.decode("latin-1", "replace")

                remaining_budget = TOTAL_TOKEN_BUDGET - total_tokens_used
                file_token_limit = min(MAX_TEXT_TOKENS_PER_FILE, remaining_budget)

                original_tokens = estimate_tokens(txt)
                txt = truncate_to_tokens(txt, file_token_limit)
                final_tokens = estimate_tokens(txt)

                truncation_info = ""
                if original_tokens > file_token_limit:
                    truncation_info = f" [обрезан: {final_tokens} из {original_tokens} токенов]"

                content.append({
                    "type": "text",
                    "text": f"Содержимое {file_name}.{ext_l}{truncation_info}:\n{txt}"
                })

                total_tokens_used += final_tokens

    content.append({"type": "text", "text": text_final})
    if photos:
        content.extend(photos)
    return content



class GPTCompletions:  # noqa: N801
    def __init__(self):
        self.client = AsyncOpenAI(api_key=NEURO_GPT_TOKEN, base_url="https://neuroapi.host/v1")
        self.history = HistoryStore()

    async def _reset_client(self):
        self.client = AsyncOpenAI(api_key=NEURO_GPT_TOKEN, base_url="https://neuroapi.host/v1")

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
            "video_urls": [],
            "audio_file": None,
            "reply_markup": None
        }
        main_bot = get_current_bot()
        from settings import logger
        from settings import get_weekday_russian

        user = await users_repository.get_user_by_user_id(user_id=user_id)
        about_user = user.context

        # 1) грузим историю из БД и строим messages



        # 5) вызов Chat Completions
        lock = await get_thread_lock(str(user_id))
        async with lock:
            try:
                stored = await self.history.load(user_id=user_id)
                messages = _map_history_to_chat_messages(stored)
                messages = _sanitize_messages_for_chat_api(messages)

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
                from settings import system_prompt
                messages = [{"role": "system", "content": system_prompt + "\n\n" + system_text}] + messages

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
                safe_content_parts = _lighten_parts_for_storage(content)  # ← вот это добавь

                human_json = {
                    "type": "human",
                    "content": safe_content_parts[0].get("text") if safe_content_parts and isinstance(
                        safe_content_parts[0],
                        dict) else (text or ""),
                    "additional_kwargs": {"content_parts": safe_content_parts},
                    "response_metadata": {},
                }


                from settings import tools
                tools_payload = _tools_for_chat_completions(tools or [])
                comp = await chat_create_with_auto_repair(
                    self.client,
                    # model=user.model_type,
                    model="gpt-5-mini",
                    messages=messages,
                    tools=tools_payload,
                    # temperature=0.7,
                    parallel_tool_calls=False,
                )
                await self.history.append(user_id=user_id, payload=human_json)
                msg = comp.choices[0].message
                tool_calls = getattr(msg, "tool_calls", None) or msg.model_extra.get("tool_calls") if hasattr(msg, "model_extra") else None
                print(tool_calls)
                # 6) если тулзы требуются — выполним и второй запрос
                if tool_calls:
                    ai_turn_json = {
                        "type": "ai",
                        "content": (msg.content or "")[:2000],  # не раздуваем историю
                        "tool_calls": [tc.model_dump() for tc in tool_calls],
                        "additional_kwargs": {},
                        "response_metadata": {},
                        "invalid_tool_calls": [],
                    }
                    await self.history.append(user_id=user_id, payload=ai_turn_json)
                    # проверки подписок/лимитов внутри run_tools_and_followup_chat
                    user_sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user.user_id)
                    max_photo_generations = user_sub.photo_generations if user_sub else 0
                    try:
                        final_images, web_answer, notif_answer, assistant_msgs, video_urls = await run_tools_and_followup_chat(
                            client=self.client,
                            model=user.model_type,
                            messages=messages + [{"role": "assistant", "content": msg.content or None, "tool_calls": [tc.model_dump() for tc in tool_calls]}],
                            tool_calls=[tc.model_dump() for tc in tool_calls],
                            user_id=user.user_id,
                            max_photo_generations=max_photo_generations,
                        )
                    except NoSubscription:
                        raise
                    except NoGenerations:
                        raise
                    # print(final_images)
                    # выдача пользователю
                    if video_urls:
                        # if user_sub:
                        #     await subscriptions_repository.use_generation(subscription_id=user_sub.id,
                        #                                                   count=len(final_images))
                        if user_sub:
                            await subscriptions_repository.use_video_generation(subscription_id=user_sub.id,
                                                                                count=1)
                        ai_json = {
                            "type": "ai",
                            "content": "video_urls:" + ", ".join(video_urls),
                            "tool_calls": [],
                            "additional_kwargs": {},
                            "response_metadata": {},
                            "invalid_tool_calls": [],
                        }
                        await self.history.append(user_id=user_id, payload=ai_json)
                        # final_content["text"] = final_text
                        final_content["video_urls"] = video_urls
                        return final_content
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
                        # assistant_text = assistant_msgs[0].get("content") or "Сгенерировал изображение"
                        # final_text = sanitize_with_links(assistant_text)
                        ai_json = {
                            "type": "ai",
                            "content": "file_ids:" + ", ".join("image_{i}.png" for i in range(len(final_images))),
                            "tool_calls": [],
                            "additional_kwargs": {},
                            "response_metadata": {},
                            "invalid_tool_calls": [],
                        }
                        await self.history.append(user_id=user_id, payload=ai_json)
                        # final_content["text"] = final_text
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
                final_content["text"] = ("В связи с большим наплывом пользователей"
                                         " наши сервера испытывают экстремальные нагрузки."
                                         " Скоро генерация изображений станет снова доступна,"
                                         " а пока можете воспользоваться другим функционалом."
                                         " Я умею немало 🤗")
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


from openai import BadRequestError

def repair_messages_for_tool_error(messages: list[dict]) -> list[dict]:
    """
    Чинит историю для Chat Completions, чтобы не было:
    'messages with role \"tool\" must be a response to a preceeding message with \"tool_calls\"'.

    Правила:
    - Убираем все ведущие 'tool' в начале истории.
    - Пропускаем (выкидываем) 'tool', если прямо перед ним нет ассистента с подходящим tool_call_id.
    - Если ассистент с tool_calls не получил подряд все tool-ответы,
      выкидываем самого ассистента и все связанные с ним tool-ы.
    - Сохраняем остальной контекст без изменений.

    На выходе — валидный для Chat Completions массив сообщений.
    """
    if not messages:
        return messages

    # 1) срежем ведущие tool
    i = 0
    while i < len(messages) and messages[i].get("role") == "tool":
        i += 1
    msgs = messages[i:]

    fixed: list[dict] = []
    pending: set[str] = set()
    collecting = False
    buffer_tools: list[dict] = []

    def _drop_open_assistant_block():
        # убрать из fixed последний ассистент и все уже добавленные tool после него
        nonlocal fixed
        while fixed and fixed[-1].get("role") == "tool":
            fixed.pop()
        if fixed and fixed[-1].get("role") == "assistant":
            fixed.pop()

    for m in msgs:
        role = m.get("role")
        if role == "assistant":
            # если предыдущий ассистент так и не «закрылся» всеми tool — выкидываем его
            if collecting and pending:
                _drop_open_assistant_block()
                pending.clear()
                collecting = False
                buffer_tools.clear()

            fixed.append(m)
            tcs = m.get("tool_calls") or []
            pending = {tc.get("id") for tc in tcs if tc.get("id")}
            collecting = bool(pending)
            buffer_tools.clear()

        elif role == "tool":
            tcid = m.get("tool_call_id")
            # корректный tool — только если прямо перед ним наш ассистент
            if collecting and tcid in pending and fixed and fixed[-1].get("role") in ("assistant", "tool"):
                fixed.append(m)
                pending.discard(tcid)
                if not pending:
                    collecting = False
            else:
                # осиротевший tool — выбрасываем
                continue

        else:
            # system / user / и пр.
            if collecting and pending:
                _drop_open_assistant_block()
                pending.clear()
                collecting = False
                buffer_tools.clear()
            fixed.append(m)

    # история закончилась, но ассистент с tool_calls не «закрылся»
    if collecting and pending:
        _drop_open_assistant_block()

    # финальная страховка: если снова начнётся с tool — срежем
    while fixed and fixed[0].get("role") == "tool":
        fixed.pop(0)

    return fixed


async def chat_create_with_auto_repair(client, *, model: str, messages: list[dict], tools=None, max_repair_attempts: int = 1, **kwargs):
    """
    Обёртка над client.chat.completions.create с авто-чинкой истории под конкретную ошибку 'role tool ... tool_calls'.
    Делает до max_repair_attempts повторов (по умолчанию 1), дальше — пробрасывает исключение.
    """
    attempt = 0
    current = messages
    while True:
        try:
            return await client.chat.completions.create(
                model=model,
                messages=current,
                tools=tools if tools else None,
                **kwargs
            )
        except BadRequestError as e:
            msg = str(e)
            # чиним ТОЛЬКО конкретный кейс с role=tool / tool_calls
            if "messages with role 'tool' must be a response to a preceeding message with 'tool_calls'" not in msg:
                raise
            if attempt >= max_repair_attempts:
                raise

            # 1) пробуем аккуратный ремонт
            repaired = repair_messages_for_tool_error(current)

            # 2) если "аккуратно" ничего не поменялось — применим брутальный фоллбек:
            # полностью выкинуть все tool-сообщения и ассистентов с tool_calls (ценой части контекста)
            if repaired == current:
                repaired = [
                    m for m in current
                    if not (m.get("role") == "tool" or (m.get("role") == "assistant" and m.get("tool_calls")))
                ]
                # и на всякий случай срезать возможный ведущий tool вновь
                while repaired and repaired[0].get("role") == "tool":
                    repaired.pop(0)

            current = repaired
            attempt += 1
            # цикл сделает повтор

