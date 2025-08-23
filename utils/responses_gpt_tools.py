# responses_gpt_tools.py

from __future__ import annotations

import asyncio
import base64
import io
import json
import mimetypes
import os
import traceback
from collections import defaultdict
from typing import Any, Optional, Sequence, Dict, List, Tuple

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
    InternalServerError,
)

from data.keyboards import subscriptions_keyboard, more_generations_keyboard, delete_notification_keyboard
from db.models import Users
from db.repository import (
    users_repository,
    subscriptions_repository,
    type_subscriptions_repository,
    generations_packets_repository,
    notifications_repository,
)
from settings import get_current_datetime_string, print_log, get_current_bot
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

# ----------------------------- shared ---------------------------------

_thread_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

class NoSubscription(Exception): ...
class NoGenerations(Exception): ...

def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


async def retrieve_with_retry(client: AsyncOpenAI, file_id: str, max_attempts: int = 4, base_delay: float = 0.5):
    attempt = 0
    while attempt < max_attempts:
        try:
            return await client.files.retrieve(file_id=file_id, timeout=3)
        except InternalServerError:
            attempt += 1
            await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
    raise RuntimeError(f"Не удалось получить файл {file_id} после {max_attempts} попыток")

async def get_thread_lock(dialog_key: str) -> asyncio.Lock:
    return _thread_locks[dialog_key]

load_dotenv(find_dotenv())
OPENAI_API_KEY: str | None = os.getenv("GPT_TOKEN") or os.getenv("OPENAI_API_KEY")
DEFAULT_IMAGE_MODEL = "gpt-image-1"
DEFAULT_IMAGE_SIZE = "1024x1024"

UNSUPPORTED_FOR_GPT_IMAGE = {"response_format", "style"}

# ----------------------------- Responses API adapter ---------------------------------

class GPTResponses:  # API через /v1/responses
    """
    Полная адаптация вашей логики на Responses API.
    Вместо thread_id используется previous_response_id (храните у пользователя).
    Встроенный веб-поиск включён через tools=[{"type":"web_search"}].
    Поиск по файлам реализован через tools=[{"type":"file_search"}] + vector store.
    """

    def __init__(self):
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.vector_store_id: str | None = None

    # --------------------- public entrypoint ---------------------

    async def send_message(
            self,
            user_id: int,
            *,
            with_audio_transcription: bool = False,
            text: str | None = None,
            image_bytes: Sequence[io.BytesIO] | None = None,
            document_bytes: Sequence[Tuple[io.BytesIO, str, str]] | None = None,
            # (buf, filename, mime_ext) — mime_ext игнорим
            document_type: str | None = None,
            audio_bytes: io.BytesIO | None = None,
            user_data: Users | None = None,
            thread_id: str | None = None,
    ) -> Dict[str, Any]:
        final_content = {"text": None, "image_files": [], "files": [], "audio_file": None, "reply_markup": None}
        main_bot = get_current_bot()
        from bot import logger
        from settings import get_weekday_russian

        user = await users_repository.get_user_by_user_id(user_id=user_id)
        # model = user.model_type
        model = "gpt-5-mini"
        about_user = (user.context or "").strip()
        base_user_text = (text or "Вот информация").strip()

        # если вообще нет входа
        if not any([base_user_text, image_bytes, document_bytes, audio_bytes]):
            final_content["text"] = "Не получен контент для обработки"
            return final_content

        # ====== КРИТИЧНО: если пришли НОВЫЕ ФАЙЛЫ — явно скажем модели, какие именно использовать ======
        attached_filenames: list[str] = [fn for _, fn, _ in (document_bytes or [])]
        if attached_filenames:
            files_note = (
                    "\n\n📎 В этом сообщении Я ПРИКРЕПИЛ файлы (используй ТОЛЬКО их и игнорируй любые старые файлы):\n- "
                    + "\n- ".join(attached_filenames)
            )
            base_user_text += files_note

        # блокировка диалога на время запроса
        dialog_key = str(user.user_id)
        lock = await get_thread_lock(dialog_key)
        async with lock:
            try:
                # 1) Собираем ТОЛЬКО текст + картинки (файлы НЕ кладём как input_file)
                content_items, _ignored_file_ids, _ignored_img_ids = await self._build_input_items(
                    base_text=base_user_text,
                    image_bytes=image_bytes,
                    document_bytes=None,  # <-- принципиально
                    audio_bytes=audio_bytes,
                )

                # 2) Если есть документы — создаём временный Vector Store и грузим файлы прямо в него
                vector_store_id = None
                if document_bytes:
                    vs = await self.client.vector_stores.create(
                        name=f"vs-user-{user_id}",
                        expires_after={"anchor": "last_active_at", "days": 1},  # авто-очистка
                    )
                    vector_store_id = vs.id

                    files_payload: list[tuple[str, io.BytesIO]] = []
                    for (doc_io, file_name, _mime_ext) in document_bytes:
                        doc_io.seek(0)
                        files_payload.append((file_name, doc_io))

                    # официальный путь: батч-аплоад + подождать индексацию
                    await self.client.vector_stores.file_batches.upload_and_poll(
                        vector_store_id=vector_store_id,
                        files=files_payload,
                    )

                # 3) Формируем tools. Если есть VS — подключаем file_search с vector_store_ids прямо в элементе инструмента
                tools: list[dict] = [{"type": "web_search"}]
                if vector_store_id:
                    tools.append({
                        "type": "file_search",
                        "vector_store_ids": [vector_store_id],
                    })
                from settings import tools as settings_tools
                for t in settings_tools:
                    tools.append({
                        "type": "function",
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                        **({"strict": True} if t.get("strict") else {})
                    })
                from settings import system_prompt
                # 4) Системный промпт
                system_prefix = (
                    f"ВАЖНАЯ ИНФОРМАЦИЯ О ВРЕМЕНИ:\n"
                    f"Текущие дата и время в Москве: {get_current_datetime_string()}\n"
                    f"Сегодня {get_weekday_russian()}\n"
                    f"ВСЕ уведомления и напоминания должны устанавливаться в московском времени!\n"
                    f"Примеры относительных дат: 'завтра', 'послезавтра', 'на следующей неделе в понедельник', 'через 30 минут'.\n\n"
                    "Если доступен file_search — опирайся на найденные по файлам фрагменты (цитируй ключевые данные) "
                    "и используй ТОЛЬКО файлы, перечисленные в сообщении пользователя выше.\n"
                ) + "\nОсновной системный промт:\n\n" + system_prompt
                if about_user:
                    system_prefix += f"\n\nИнформация о пользователе:\n{about_user}\n\n"

                # 5) Для НОВЫХ ДОКОВ рвём контекст (чтобы не тянуть старые файлы/цитаты);
                # иначе продолжаем тред через previous_response_id
                previous_response_id = None if document_bytes else user.last_response_id

                request_kwargs: Dict[str, Any] = {
                    "model": model,
                    "input": [
                        {"role": "system", "content": system_prefix},
                        {"role": "user", "content": content_items},
                    ],
                    "tools": tools,
                    "tool_choice": "auto",
                }
                if previous_response_id:
                    request_kwargs["previous_response_id"] = previous_response_id

                # 6) Первый вызов Responses API
                try:
                    resp = await self._create_response(**request_kwargs)
                except BadRequestError:
                    if previous_response_id:
                        try:
                            await users_repository.update_last_response_id_by_user_id(
                                user_id=user.user_id, last_response_id=None
                            )
                        except Exception:
                            pass
                        request_kwargs.pop("previous_response_id", None)
                        resp = await self._create_response(**request_kwargs)
                    else:
                        raise

                # 7) Цикл инструментов — важно сохранить те же tools (чтобы file_search оставался доступен)
                delete_message = None
                self._followup_tools = tools
                resp, tool_side_effects = await self._tool_call_loop(
                    first_response=resp,
                    user=user,
                    max_photo_generations=await self._get_remaining_generations(user),
                )

                # 8) Сохраняем last_response_id (уже новый, т.к. могли порвать контекст выше)
                try:
                    await users_repository.update_last_response_id_by_user_id(
                        user_id=user.user_id, last_response_id=resp.id
                    )
                except Exception:
                    pass

                # 9) Разруливаем побочные эффекты/результаты
                if tool_side_effects.get("delete_message"):
                    delete_message = tool_side_effects["delete_message"]

                if tool_side_effects.get("web_answer"):
                    if delete_message:
                        await delete_message.delete()
                    final_content["text"] = sanitize_with_links(tool_side_effects["web_answer"])
                    return final_content

                if tool_side_effects.get("notif_answer"):
                    if delete_message:
                        await delete_message.delete()
                    final_content["text"] = sanitize_with_links(tool_side_effects["notif_answer"])
                    if "✅" in final_content["text"]:
                        user_notifications = await notifications_repository.get_active_notifications_by_user_id(
                            user_id=user_id
                        )
                        if user_notifications:
                            final_content["reply_markup"] = delete_notification_keyboard(user_notifications[-1].id)
                    return final_content

                if tool_side_effects.get("final_images"):
                    if delete_message:
                        await delete_message.delete()
                    imgs = tool_side_effects["final_images"]
                    if imgs:
                        await self._consume_generations(user, count=len(imgs))
                        final_text = self._extract_text(resp) or "Сгенерировал изображение"
                        final_content["text"] = sanitize_with_links(final_text)
                        final_content["image_files"] = imgs
                        return final_content

                files_payload = await self._maybe_collect_file_attachments_from_response(resp)
                if files_payload:
                    if delete_message:
                        await delete_message.delete()
                    final_content["files"] = files_payload
                    return final_content

                output_text = self._extract_text(resp) or "Произошла непредвиденная ошибка, попробуй еще раз!"
                if with_audio_transcription:
                    audio_data = await self.generate_audio_by_text(output_text)
                    final_content["text"] = sanitize_with_links(output_text)
                    final_content["audio_file"] = audio_data
                    return final_content

                final_content["text"] = sanitize_with_links(output_text)
                return final_content

            except NoSubscription:
                raise
            except NoGenerations:
                raise
            except Exception:
                await self._reset_client()
                logger.log("GPT_ERROR", f"{user_id} | Ошибка в ответе gpt: {traceback.format_exc()}")
                print_log(message=f"{user_id} | Ошибка в ответе gpt: {traceback.format_exc()}")
                final_content["text"] = (
                    "Произошла непредвиденная ошибка, попробуй еще раз! "
                    "Твой запрос может содержать контент, который не разрешен нашей системой безопасности"
                )
                return final_content

    # --------------------- tools orchestration ---------------------

    def _compose_tools(self, *, enable_file_search: bool, enable_web_search: bool) -> list[dict]:
        tools: list[dict] = []
        if enable_web_search:
            tools.append({"type": "web_search"})
        if enable_file_search:
            tools.append({"type": "file_search"})  # ВАЖНО: включаем только если есть VS
        from settings import tools as settings_tools
        for t in settings_tools:
            tools.append({
                "type": "function",
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                **({"strict": True} if t.get("strict") else {})
            })
        return tools

    def _guess_mime(self, filename: str, default: str = "application/octet-stream") -> str:
        """
        Нормальный определитель MIME для любых офисных/текстовых/архивных форматов.
        """
        # Встроенный маппинг на случай, если mimetypes вернёт None
        custom = {
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".csv": "text/csv",
            ".tsv": "text/tab-separated-values",
            ".md": "text/markdown",

            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".rtf": "application/rtf",

            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",

            ".ppt": "application/vnd.ms-powerpoint",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",

            ".json": "application/json",
            ".xml": "application/xml",
            ".html": "text/html",
            ".htm": "text/html",

            ".zip": "application/zip",
            ".gz": "application/gzip",
            ".7z": "application/x-7z-compressed",
            ".rar": "application/vnd.rar",
        }
        ext = os.path.splitext(filename)[1].lower()
        if ext in custom:
            return custom[ext]
        guessed, _ = mimetypes.guess_type(filename)
        return guessed or default

    async def _upload_for_input_file(self, file_obj: io.BytesIO, filename: str, mime: str) -> str:
        """
        Грузим файл в Files API корректно для блоков input_file.
        Сначала пробуем с purpose='user_data' (рекомендовано в срочных доках),
        если SDK/аккаунт ругнётся — фоллбек на 'assistants'.
        Возвращает file_id.
        """
        file_obj.seek(0)
        try:
            up = await self.client.files.create(file=(filename, file_obj, mime), purpose="user_data")
            return up.id
        except BadRequestError:
            # фоллбек на старый purpose
            up = await self.client.files.create(file=(filename, file_obj, mime), purpose="assistants")
            return up.id

    async def _tool_call_loop(
        self,
        *,
        first_response,
        user: Users,
        max_photo_generations: int | None,
    ):
        main_bot = get_current_bot()

        delete_message = None
        final_images: List[bytes] = []
        web_answer: Optional[str] = None
        notif_answer: Optional[str] = None

        response = first_response
        safety_counter = 0

        while True:
            safety_counter += 1
            if safety_counter > 8:
                break

            tool_calls = self._extract_tool_calls(response)
            if not tool_calls:
                break

            custom_names = self._custom_function_names()

            # Показ «прогресса»
            for tc in tool_calls:
                fname = getattr(tc, "name", None) or tc.get("name")
                if fname in ("generate_image", "edit_image_only_with_peoples", "fitting_clothes"):
                    # проверки подписок/лимитов
                    sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user.user_id)
                    sub_types = await type_subscriptions_repository.select_all_type_subscriptions()
                    type_sub = await type_subscriptions_repository.get_type_subscription_by_id(type_id=sub.type_subscription_id) if sub else None
                    if sub is None or (type_sub and type_sub.plan_name == "Free"):
                        from settings import sub_text
                        await main_bot.send_message(
                            chat_id=user.user_id,
                            text="🚨К сожалению, данная функция доступна только по подписке\n\n" + sub_text,
                            reply_markup=subscriptions_keyboard(sub_types).as_markup(),
                        )
                        raise NoSubscription("No active subscription")
                    if fname != "fitting_clothes":
                        if sub.photo_generations <= 0:
                            generations_packets = await generations_packets_repository.select_all_generations_packets()
                            from settings import buy_generations_text
                            await main_bot.send_message(
                                chat_id=user.user_id,
                                text=buy_generations_text,
                                reply_markup=more_generations_keyboard(generations_packets).as_markup(),
                            )
                            raise NoGenerations("No generations left")
                        delete_message = await main_bot.send_message(chat_id=user.user_id, text="🎨Начал работу над изображением, немного магии…")
                elif fname == "add_notification":
                    delete_message = await main_bot.send_message(chat_id=user.user_id, text="🖌Начал настраивать напоминание, это не займет много времени...")
                elif fname == "search_web":
                    # в Responses API встроенный web_search, ваш кастом удалён; этот кейс может не прийти
                    delete_message = await main_bot.send_message(chat_id=user.user_id, text="🔍Начал поиск в интернете, анализирую страницы...")

            # Выполняем вызовы
            tool_results: List[dict] = []
            images_counter = 0
            for tc in tool_calls:
                name, call_id, args = self._split_tool_call(tc)
                result_payload = None
                if name not in custom_names:
                    # можно просто пропустить или залогировать
                    # встроенные web_search/file_search обрабатываются платформой
                    continue
                if name == "add_notification":
                    result_payload = {"text": await self._handle_add_notification(user.user_id, args)}
                    notif_answer = result_payload["text"]
                elif name in ("generate_image", "edit_image_only_with_peoples"):
                    imgs = await self._handle_image_tools(user_id=user.user_id, name=name, args=args, max_photo_generations=max_photo_generations)
                    if isinstance(imgs, list) and imgs:
                        final_images.extend(imgs)
                        images_counter += len(imgs)
                    result_payload = {"file_ids": await self._upload_images_as_files(imgs)}
                elif name == "fitting_clothes":
                    msg = await self._handle_fitting_clothes(user_id=user.user_id, args=args)
                    if isinstance(msg, str):
                        result_payload = {"text": msg}
                    else:
                        final_images.extend(msg)
                        result_payload = {"file_ids": await self._upload_images_as_files(msg)}
                elif name == "search_web":
                    # оставлено для совместимости; фактически web_search встроен в модель
                    result_payload = {"text": "Поиск выполнен встроенным инструментом web_search"}
                    web_answer = "Поиск выполнен встроенным инструментом web_search"
                else:
                    # неизвестный tool — игнор
                    result_payload = {"text": "ignored"}

                tool_results.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result_payload, ensure_ascii=False),  # строка!
                })

            # Передаём результаты инструментов и продолжаем цепочку с previous_response_id
            # СТАЛО
            response = await self._create_response(
                model=user.model_type,
                previous_response_id=(first_response.id if response.id == first_response.id else response.id),
                input=tool_results,
                tools=getattr(self, "_followup_tools", [{"type": "web_search"}]),
            )

        return response, {
            "delete_message": delete_message,
            "final_images": final_images,
            "web_answer": web_answer,
            "notif_answer": notif_answer,
        }

    def _custom_function_names(self) -> set[str]:
        from settings import tools as settings_tools
        return {t["name"] for t in settings_tools}

    # --------------------- low-level Responses helpers ---------------------

    async def _create_response(self, **kwargs):
        for attempt in range(1, 6):
            try:
                return await self.client.responses.create(**kwargs)
            except (APITimeoutError, APIConnectionError, APIStatusError, RateLimitError):
                if attempt == 5:
                    raise
                await asyncio.sleep(1.5 ** attempt)
            except (AuthenticationError, PermissionDeniedError, BadRequestError):
                raise

    def _extract_tool_calls(self, resp) -> List[dict]:
        calls: List[dict] = []
        for item in getattr(resp, "output", []) or []:
            t = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
            if t == "function_call":  # Responses API возвращает function_call
                name = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
                call_id = item.get("call_id") if isinstance(item, dict) else getattr(item, "call_id", None)
                args = item.get("arguments") if isinstance(item, dict) else getattr(item, "arguments", None)
                calls.append({"name": name, "call_id": call_id, "arguments": args})
        return calls

    def _split_tool_call(self, tc: dict) -> Tuple[str, str, dict]:
        name = tc.get("name") or ""
        call_id = tc.get("call_id") or ""
        raw = tc.get("arguments")
        if isinstance(raw, dict):
            args = raw
        else:
            try:
                args = json.loads(raw or "{}")
            except json.JSONDecodeError:
                first_obj = (raw or "").split('}', 1)[0] + '}'
                args = json.loads(first_obj)
        return name, call_id, args

    def _extract_text(self, resp) -> Optional[str]:
        # Responses API: итоговый текст лежит в output как message-блок(и)
        texts: List[str] = []
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", None) == "message":
                # item.content может быть массивом токенов; пытаемся слить в текст
                parts = getattr(item, "content", None)
                if isinstance(parts, list):
                    s = []
                    for p in parts:
                        if isinstance(p, dict) and p.get("type") == "output_text" and p.get("text"):
                            s.append(p["text"])
                        elif hasattr(p, "type") and getattr(p, "type") == "output_text":
                            s.append(getattr(p, "text", "") or "")
                    if s:
                        texts.append(" ".join(s).strip())
        return (texts[0] if texts else None)

    async def _maybe_collect_file_attachments_from_response(self, resp) -> Optional[List[dict]]:
        out = []
        try:
            for item in getattr(resp, "output", []) or []:
                if getattr(item, "type", None) == "message":
                    for p in getattr(item, "content", []) or []:
                        # изображения, файлы как file_id
                        fid = None
                        if isinstance(p, dict) and p.get("type") in ("output_image", "output_file"):
                            fid = p.get("file_id")
                        elif hasattr(p, "type") and getattr(p, "type") in ("output_image", "output_file"):
                            fid = getattr(p, "file_id", None)
                        if fid:
                            fmeta = await self.client.files.retrieve(file_id=fid)
                            data = await self.client.files.content(file_id=fid)
                            b = await data.aread()
                            name = (fmeta.filename or "file.bin")
                            if not name.lower().endswith(".png") and getattr(p, "type", None) == "output_image":
                                name += ".png"
                            out.append({"filename": name, "bytes": b})
            return out or None
        except Exception:
            return None

    # --------------------- content builders ---------------------

    async def _build_input_items(
            self,
            *,
            base_text: str,
            image_bytes: Sequence[io.BytesIO] | None,
            document_bytes: Sequence[Tuple[io.BytesIO, str, str]] | None,
            audio_bytes: io.BytesIO | None,
    ) -> Tuple[List[dict], List[str], List[str]]:
        """
        Картинки: как data URL (image_url).
        ФАЙЛЫ ЛЮБЫХ ФОРМАТОВ: загружаем в Files API и ВОЗВРАЩАЕМ их file_id,
        НО НЕ кладём их в content как input_file (это и ломалось на не-PDF).
        Дальше эти file_id уйдут в Vector Store (File Search).
        """
        content: List[dict] = []
        file_ids: List[str] = []
        image_file_ids: List[str] = []

        # 1) картинки — без изменений
        if image_bytes:
            for img_io in image_bytes:
                img_io.seek(0)
                b64 = base64.b64encode(img_io.read()).decode("utf-8")
                content.append({
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{b64}",
                })

        # 2) текст
        text = f"Сегодня - {get_current_datetime_string()} по Москве.\n\n{base_text}"
        content.append({"type": "input_text", "text": text})

        # 3) файлы → Files API (purpose='assistants'), собираем только их id
        if document_bytes:
            for (doc_io, file_name, _mime_ext) in document_bytes:
                # MIME можно не указывать — SDK сам проставит; если хочешь — можно угадать из имени
                doc_io.seek(0)
                up = await self.client.files.create(
                    file=(file_name, doc_io),
                    purpose="assistants",
                )
                file_ids.append(up.id)

        # лимит контента
        if len(content) > 12:
            content = content[-12:]

        return content, file_ids, image_file_ids

    # --------------------- vector store / file_search ---------------------

    async def _sync_vector_store(self, file_ids: List[str]) -> str:
        """
        Кладём file_ids в Vector Store и ждём, пока батч проиндексируется.
        Возвращаем vector_store_id.
        """
        # создаём/переиспользуем общий VS
        if not self.vector_store_id:
            vs = await self.client.vector_stores.create(name="vs-responses")
            self.vector_store_id = vs.id

        if not file_ids:
            return self.vector_store_id

        # создаём батч из уже загруженных в Files API файлов
        batch = await self.client.vector_stores.file_batches.create(
            vector_store_id=self.vector_store_id,
            file_ids=file_ids,
        )

        # ждём завершения индексации батча
        # статус: "in_progress" -> "completed" | "failed" | "cancelled"
        while True:
            b = await self.client.vector_stores.file_batches.retrieve(
                vector_store_id=self.vector_store_id,
                batch_id=batch.id,
            )
            if getattr(b, "status", None) in ("completed", "failed", "cancelled"):
                break
            await asyncio.sleep(0.5)

        return self.vector_store_id

    # --------------------- tool handlers ---------------------

    async def _handle_add_notification(self, user_id: int, args: dict) -> str:
        when_send_str, text_notification = args.get("when_send_str"), args.get("text_notification")
        try:
            await schedule_notification(user_id=user_id, when_send_str=when_send_str, text_notification=text_notification)
            return f"✅ Отлично! Уведомление установлено на {when_send_str} по московскому времени\n\n📝 Текст напоминания: {text_notification}"
        except NotificationLimitError:
            active = await notifications_repository.get_active_notifications_by_user_id(user_id)
            return f"❌ Превышен лимит уведомлений. У вас уже есть {len(active)} активных уведомлений. Максимум: 10."
        except NotificationFormatError:
            return "❌ Неверный формат даты/времени. Используйте: ГГГГ-ММ-ДД ЧЧ:ММ:СС"
        except NotificationDateTooFarError:
            return "❌ Дата слишком далекая. Можно устанавливать уведомления максимум до 2030 года."
        except NotificationDateInPastError:
            return "❌ Указанный год уже прошел. Укажите дату в будущем."
        except NotificationPastTimeError:
            return "❌ Указанное время уже прошло. Укажите время в будущем. Сейчас московское время."
        except NotificationTextTooShortError:
            return "❌ Текст уведомления слишком короткий (минимум 3 символа)."
        except NotificationTextTooLongError:
            return "❌ Текст уведомления слишком длинный (макс. 500 символов)."
        except Exception:
            return "❌ Неожиданная ошибка при создании уведомления. Попробуйте ещё раз."

    async def _handle_image_tools(self, *, user_id: int, name: str, args: dict, max_photo_generations: int | None) -> List[bytes]:
        image_client = AsyncOpenAIImageClient()
        # подхватываем последние фото пользователя из TG, если были
        user = await users_repository.get_user_by_user_id(user_id=user_id)
        photo_bytes = []
        if user.last_image_id:
            for pid in user.last_image_id.split(", "):
                main_bot = get_current_bot()
                buf = io.BytesIO()
                try:
                    await main_bot.download(pid, destination=buf)
                    buf.seek(0)
                    photo_bytes.append(buf.read())
                except:
                    pass

        if name == "generate_image":
            try:
                n_req = args.get("n", 1)
                if max_photo_generations is not None:
                    n = min(n_req, max_photo_generations)
                else:
                    n = n_req
                kwargs = {
                    "prompt": args["prompt"],
                    "n": n,
                    "size": args.get("size", DEFAULT_IMAGE_SIZE),
                    "quality": args.get("quality", "low"),
                }
                if args.get("edit_existing_photo"):
                    kwargs["images"] = [("image.png", io.BytesIO(b), "image/png") for b in photo_bytes]
                return await image_client.generate(**kwargs)
            except:
                return []

        if name == "edit_image_only_with_peoples":
            try:
                prompt = (args.get("prompt") or "").strip()[:400]
                if not prompt:
                    return []
                return [await generate_image_bytes(prompt=args.get("prompt"), ratio=args.get("ratio"),
                                                   images=photo_bytes if len(photo_bytes) <= 3 else photo_bytes[:3])]
            except:
                from bot import logger
                logger.log("GPT_ERROR", f"{user_id} | Ошибка edit_image_only_with_peoples: {traceback.format_exc()}")
                print_log(message=f"{user_id} | Ошибка edit_image_only_with_peoples: {traceback.format_exc()}")
                return []

        return []

    async def _handle_fitting_clothes(self, *, user_id: int, args: dict) -> str | List[bytes]:
        fitroom_client = FitroomClient()
        cloth_type = (args.get("cloth_type") or "full").strip()
        swap_photos = bool(args.get("swap_photos") or False)

        user = await users_repository.get_user_by_user_id(user_id=user_id)
        photos = []
        if user.last_image_id:
            for pid in user.last_image_id.split(", "):
                main_bot = get_current_bot()
                buf = io.BytesIO()
                try:
                    await main_bot.download(pid, destination=buf)
                    buf.seek(0)
                    photos.append(buf.read())
                except:
                    pass

        if len(photos) != 2:
            return "Дорогой друг, пришли фото человека и фото одежды для примерки одним сообщением! Ровно две фотографии!"
        model_bytes = photos[1] if swap_photos else photos[0]
        cloth_bytes = photos[0] if swap_photos else photos[1]

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

    async def _upload_images_as_files(self, images: List[bytes]) -> List[str]:
        file_ids: List[str] = []
        for idx, img in enumerate(images or []):
            f = await self.client.files.create(file=(f"result_{idx}.png", io.BytesIO(img), "image/png"), purpose="vision")
            file_ids.append(f.id)
        return file_ids

    async def _get_remaining_generations(self, user: Users) -> Optional[int]:
        sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user.user_id)
        return (sub.photo_generations if sub else None)

    async def _consume_generations(self, user: Users, count: int):
        sub = await subscriptions_repository.get_active_subscription_by_user_id(user_id=user.user_id)
        if sub:
            await subscriptions_repository.use_generation(subscription_id=sub.id, count=count)

    # --------------------- TTS / ASR ---------------------

    @staticmethod
    async def generate_audio_by_text(text: str) -> io.BytesIO:
        url = "https://api.openai.com/v1/audio/speech"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "gpt-4o-mini-tts", "input": text, "voice": "shimmer", "instructions": "Speak dramatic", "response_format": "mp3"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=30) as r:
                if r.status == 200:
                    return io.BytesIO(await r.read())
                raise RuntimeError(f"TTS error {r.status}: {await r.text()}")

    @staticmethod
    async def transcribe_audio(audio_bytes: io.BytesIO, language: str = "ru") -> str:
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        audio_bytes.name = "audio.mp3"
        data = {"file": audio_bytes, "model": "whisper-1", "language": language}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data, timeout=60) as r:
                if r.status == 200:
                    j = await r.json()
                    return j.get("text", "")
                raise RuntimeError(f"Transcription error {r.status}: {await r.text()}")

    # --------------------- maintenance ---------------------

    async def _reset_client(self):
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    # === NEW ===
    async def _prepare_file_scope(
            self,
            user_id: int,
            document_bytes: Sequence[tuple[io.BytesIO, str, str]] | None,
    ) -> tuple[Optional[str], list[str]]:
        """
        Если в сообщении есть файлы – создаёт временный Vector Store,
        загружает туда файлы и ждёт индексацию. Возвращает (vs_id, file_names).
        """
        if not document_bytes:
            return None, []

        # 1) создаём эпhemeral VS (само удалится, чтобы не копить мусор)
        vs = await self.client.vector_stores.create(
            name=f"vs-user-{user_id}-{int(asyncio.get_running_loop().time() * 1000)}",
            expires_after={"anchor": "last_active_at", "days": 1},  # опционально
        )
        vector_store_id = vs.id

        # 2) готовим список файлов для батч-загрузки
        files_payload = []
        file_names: list[str] = []
        for (doc_io, file_name, _ext) in document_bytes:
            doc_io.seek(0)
            files_payload.append((file_name, doc_io))
            file_names.append(file_name)

        # 3) грузим и ЖДЁМ индексации (официальный путь upload_and_poll)
        await self.client.vector_stores.file_batches.upload_and_poll(
            vector_store_id=vector_store_id,
            files=files_payload,
        )
        return vector_store_id, file_names

    # === NEW ===
    def _append_attached_filenames_to_prompt(self, base_text: str, file_names: list[str]) -> str:
        """
        Добавляет в пользовательский текст явный список имён файлов + инструкцию,
        чтобы модель НЕ обращалась к прошлым файлам.
        """
        if not file_names:
            return base_text

        list_str = "\n".join(f"- {n}" for n in file_names)
        suffix = (
            "\n\n📎 В этом сообщении Я ПРИКРЕПИЛ файлы. "
            "Проанализируй и используй ТОЛЬКО эти файлы; любые файлы из прошлых сообщений игнорируй.\n"
            f"{list_str}\n"
        )
        return (base_text or "") + suffix

