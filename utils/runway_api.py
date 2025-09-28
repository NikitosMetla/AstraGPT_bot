# import asyncio
# import math
# import os
# import base64
# import logging
# from typing import Sequence, Optional
#
# import aiohttp
# from dotenv import load_dotenv, find_dotenv
# from runwayml import AsyncRunwayML
# from runwayml.types.text_to_image_create_params import ContentModeration
#
# load_dotenv(find_dotenv())
# _RW = AsyncRunwayML(api_key=os.getenv("RUNWAY_KEY"))
# _HTTP_SESSION: Optional[aiohttp.ClientSession] = None
#
# # Настройка логгера
# logger = logging.getLogger("runway_api")
# logger.setLevel(logging.DEBUG)  # или INFO
# handler = logging.StreamHandler()
# handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
# logger.addHandler(handler)
#
#
# def _to_data_uri(data: bytes, mime: str = "image/jpeg") -> str:
#     """Преобразует байты изображения в data URI."""
#     return f"data:{mime};base64,{base64.b64encode(data).decode()}"
#
# async def _session() -> aiohttp.ClientSession:
#     global _HTTP_SESSION
#     if _HTTP_SESSION is None:
#         _HTTP_SESSION = aiohttp.ClientSession()
#     return _HTTP_SESSION
#
# from io import BytesIO
# from PIL import Image, ImageOps
#
# MIN_AR, MAX_AR = 0.5, 2.0          # требования Runway
# MAX_SIDE       = 8000              # px – лимит Runway
#
# def prepare_ref(raw: bytes) -> bytes:
#     img = Image.open(BytesIO(raw)).convert("RGB")
#     w, h = img.size
#     ar   = w / h
#
#     # ограничение максимального разрешения
#     if max(w, h) > MAX_SIDE:
#         scale = MAX_SIDE / max(w, h)
#         img   = img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
#         w, h  = img.size
#         ar    = w / h
#
#     # паддинг до MIN_AR
#     if ar <= MIN_AR:
#         new_w = math.floor(h * MIN_AR) + 1
#         total_pad = new_w - w
#         pad_left  = total_pad // 2
#         pad_right = total_pad - pad_left
#         img = ImageOps.expand(img, (pad_left, 0, pad_right, 0), fill=(0,0,0))
#
#     # паддинг до MAX_AR
#     elif ar >= MAX_AR:
#         new_h = math.floor(w / MAX_AR) + 1
#         total_pad = new_h - h
#         pad_top    = total_pad // 2
#         pad_bottom = total_pad - pad_top
#         img = ImageOps.expand(img, (0, pad_top, 0, pad_bottom), fill=(0,0,0))
#
#     w2, h2 = img.size
#     ar2    = w2 / h2
#     assert MIN_AR < ar2 < MAX_AR, f"AR всё ещё вне диапазона: {ar2:.3f}"
#
#     buf = BytesIO()
#     img.save(buf, format="JPEG", quality=95)
#     return buf.getvalue()
#
#
# async def generate_image_bytes(
#     prompt: str,
#     images: Sequence[bytes] | None = None,
#     *,
#     ratio: str = "1920:1080",
#     poll_interval: float = 1.0,
#     timeout: float = 240.0,
#     max_poll_interval: float = 15.0,
#     max_retries: int = 3,
# ) -> bytes:
#     import random
#
#     # логируем вход
#     logger.info(f"generate_image_bytes called: prompt={prompt!r}, ratio={ratio}, images={'yes' if images else 'no'}")
#
#     if ratio is None:
#         ratio = "1024:1024"
#     allowed = {
#         "1920:1080","1024:1024","1080:1920","1360:768","1080:1080",
#         "1168:880","1440:1080","1080:1440","1808:768","2112:912"
#     }
#     if ratio not in allowed:
#         logger.warning(f"ratio {ratio} not in allowed, defaulting to 1024:1024")
#         ratio = "1024:1024"
#
#     refs = [{"uri": _to_data_uri(prepare_ref(img)), "tag": f"ref{i}"} for i, img in enumerate(images)] if images else None
#
#     TERMINAL_OK   = {"SUCCEEDED"}
#     TERMINAL_FAIL = {"FAILED", "CANCELED", "REJECTED"}
#     WAITING = {
#         "PENDING", "QUEUED", "RUNNING", "PROCESSING",
#         "SCHEDULED", "WAITING", "THROTTLED", "RATE_LIMITED"
#     }
#
#     last_error: Optional[str] = None
#
#     for attempt in range(1, max_retries + 2):
#         logger.info(f"Attempt {attempt}/{max_retries+1} — creating task")
#         try:
#             if refs:
#                 task_response = await _RW.text_to_image.create(
#                     model="gen4_image",
#                     ratio=ratio,
#                     prompt_text=prompt,
#                     reference_images=refs,
#                     content_moderation={"publicFigureThreshold": "low"},
#                 )
#             else:
#                 task_response = await _RW.text_to_image.create(
#                     model="gen4_image",
#                     ratio=ratio,
#                     prompt_text=prompt,
#                     # content_moderation={"publicFigureThreshold": "low"},
#                 )
#         except Exception as e:
#             msg = str(e).lower()
#             logger.warning(f"Error creating task: {e}")
#             if ("429" in msg) or ("rate" in msg) or ("throttle" in msg):
#                 if attempt <= max_retries:
#                     cooldown = 20.0 + attempt * 2.0 + random.uniform(0, 2)
#                     logger.warning(f"Rate limit or throttled at create; sleeping {cooldown:.1f}s and retrying...")
#                     await asyncio.sleep(cooldown)
#                     last_error = f"Create throttled: {type(e).__name__}: {e}"
#                     continue
#             raise
#
#         task_id = task_response.id
#         logger.info(f"Task created: id={task_id}")
#
#         loop = asyncio.get_running_loop()
#         deadline = loop.time() + timeout
#         interval = poll_interval
#
#         try:
#             while True:
#                 task = await _RW.tasks.retrieve(task_id)
#                 status = (task.status or "").upper()
#                 details = getattr(task, "error", None) or getattr(task, "failure_reason", None) or getattr(task, "message", None)
#                 meta = getattr(task, "metadata", None) or {}
#                 if details:
#                     last_error = str(details)
#
#                 logger.debug(f"Polled status: id={task_id}, status={status}, last_error={last_error}")
#
#                 if status in TERMINAL_OK:
#                     logger.info(f"Task succeeded: id={task_id}")
#                     break
#                 if status in TERMINAL_FAIL:
#                     logger.error(f"Task failed: id={task_id}, status={status}, details={last_error}")
#                     raise RuntimeError(f"Runway task failed: {status}, {last_error or ''}")
#
#                 now = loop.time()
#                 if now > deadline:
#                     logger.error(f"Timeout waiting for task: id={task_id}, status={status}")
#                     raise TimeoutError(f"Generation exceeded time limit ({timeout:.0f}s)")
#
#                 retry_after = None
#                 if isinstance(meta, dict):
#                     for key in ("retry_after", "retryAfter", "retryAfterSec", "retry_after_sec", "throttle_seconds", "cooldown"):
#                         if key in meta:
#                             retry_after = meta[key]
#                             break
#                 if retry_after is None and hasattr(task, "retry_after"):
#                     retry_after = getattr(task, "retry_after")
#
#                 if status in {"THROTTLED", "RATE_LIMITED"}:
#                     cooldown = float(retry_after) if retry_after else 18.0
#                     cooldown += random.uniform(0.0, 2.0)
#                     logger.warning(f"Task id={task_id} THROTTLED; sleeping {cooldown:.1f}s")
#                     await asyncio.sleep(min(cooldown, max(0, deadline - now)))
#                     interval = max(poll_interval, min(interval, 2.0))
#                 else:
#                     sleep_for = min(interval, max(0, deadline - now))
#                     logger.debug(f"Waiting {sleep_for:.2f}s before next poll for id={task_id}")
#                     await asyncio.sleep(sleep_for)
#                     interval = min(max_poll_interval, interval * 1.5) + random.uniform(0.0, 0.3)
#
#             if not task.output or not isinstance(task.output, (list, tuple)) or not task.output[0]:
#                 logger.error(f"No output returned for task id={task_id}")
#                 raise RuntimeError("Runway returned empty output list")
#
#             url = task.output[0]
#             logger.info(f"Downloading result for task id={task_id}")
#             session = await _session()
#             async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
#                 resp.raise_for_status()
#                 data = await resp.read()
#             logger.info(f"Download complete for task id={task_id}")
#             return data
#
#         except (TimeoutError, aiohttp.ClientError, RuntimeError) as e:
#             logger.warning(f"Attempt {attempt} for task id {task_id} failed: {e}")
#             if attempt <= max_retries:
#                 await asyncio.sleep(1.0 + attempt * 0.5)
#                 last_error = f"{type(e).__name__}: {e}"
#                 continue
#             logger.error(f"All {max_retries+1} attempts failed: last_error={last_error}")
#             raise TimeoutError(f"Runway generation failed after {attempt} attempt(s). Last error: {last_error or e}") from e
#


# runway_api.py (ключевые фрагменты)

# runway_api.py — асинхронный клиент Runway Gen-4 Image с корректными ретраями и понятными ошибками
from __future__ import annotations

import asyncio
import base64
import logging
import math
import os
import random
import traceback
from io import BytesIO
from typing import Optional, Sequence

import aiohttp
from PIL import Image, ImageOps
from runwayml import (
    AsyncRunwayML,
    APIStatusError,        # 4xx/5xx HTTP
    APIConnectionError,    # сетевые ошибки/таймауты соединения
    RateLimitError,        # 429
    DefaultAsyncHttpxClient,
)

# ----------------------- Конфигурация клиента и логирование -----------------------
RUNWAY_KEY = os.getenv("RUNWAY_KEY")
client = AsyncRunwayML(
    api_key=RUNWAY_KEY,
    http_client=DefaultAsyncHttpxClient(),  # официальный async backend (httpx)
    timeout=60.0,       # SDK поддерживает timeouts
    max_retries=2,      # и базовые ретраи на уровне клиента
)

# ----------------------- Утилиты для изображений -----------------------
MIN_AR, MAX_AR, MAX_SIDE = 0.5, 2.0, 8000  # рекомендации по AR/пикселям
_ALLOWED_RATIOS = {
    "1920:1080", "1080:1920", "1024:1024", "1360:768",
    "1080:1080", "1168:880", "1440:1080", "1080:1440", "1808:768", "2112:912",
}

SAFETY_FAILURE_HINTS = {
    # препроцессинг текста: модерация сработала ещё до инференса
    "INPUT_PREPROCESSING.SAFETY.TEXT": (
        "Текст запроса отклонён модерацией на этапе препроцессинга. "
        "Смягчите формулировки, избегайте упоминаний публичных персон, "
        "насилия и других чувствительных тем."
    ),
    # при желании добавьте и другие встречающиеся коды:
    "SAFETY.INPUT.TEXT": (
        "Текст запроса отклонён модерацией. Измените формулировки, избегайте упоминаний публичных персон, "
        "насилия и других чувствительных тем."
    ),
    "SAFETY.INPUT.IMAGE": (
        "Отправленное вами изображение отклонено нашей модерацией. Уберите проблемное изображение,"
        " которое потенциально могут выходить за рамки норм."
    )
}

def format_failure_human(status: str, code: Optional[str], msg: Optional[str]) -> str:
    """Готовим человекочитаемое сообщение для логов/UI."""
    base = f"status={status}"
    if code:
        base += f", code={code}"
    if msg:
        base += f", message={msg}"
    hint = SAFETY_FAILURE_HINTS.get(code or "", "")
    return f"{base}. {hint}".strip()

def _to_data_uri(data: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"

MIN_AR, MAX_AR = 0.5, 2.0          # требования Runway
MAX_SIDE       = 8000              # px – лимит Runway

def prepare_ref(raw: bytes) -> bytes:
    img = Image.open(BytesIO(raw)).convert("RGB")
    w, h = img.size
    ar   = w / h

    # ограничение максимального разрешения
    if max(w, h) > MAX_SIDE:
        scale = MAX_SIDE / max(w, h)
        img   = img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
        w, h  = img.size
        ar    = w / h

    # паддинг до MIN_AR (строго > MIN_AR)
    if ar <= MIN_AR:
        # new_width > h * MIN_AR
        new_w = math.floor(h * MIN_AR) + 1
        total_pad = new_w - w
        pad_left  = total_pad // 2
        pad_right = total_pad - pad_left
        img = ImageOps.expand(img, (pad_left, 0, pad_right, 0), fill=(0,0,0))

    # паддинг до MAX_AR (строго < MAX_AR)
    elif ar >= MAX_AR:
        # new_height > w / MAX_AR
        new_h = math.floor(w / MAX_AR) + 1
        total_pad = new_h - h
        pad_top    = total_pad // 2
        pad_bottom = total_pad - pad_top
        img = ImageOps.expand(img, (0, pad_top, 0, pad_bottom), fill=(0,0,0))

    # проверяем, что соотношение теперь в допустимом «открытом» промежутке
    w2, h2 = img.size
    ar2    = w2 / h2
    assert MIN_AR < ar2 < MAX_AR, f"AR всё ещё вне диапазона: {ar2:.3f}"

    # сохраняем в JPEG ≤95 качества
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()

# ----------------------- Исключение с понятной причиной FAIL -----------------------
class RunwayTaskFailed(RuntimeError):
    """Исключение, содержащее статус/код/сообщение причины провала задачи."""
    def __init__(self, status: str, code: Optional[str], message: Optional[str]):
        self.status = status
        self.code = code
        self.message = message
        detail = f"status={status}"
        if code:
            detail += f", code={code}"
        if message:
            detail += f", message={message}"
        super().__init__(f"Runway task failed: {detail}")

def _extract_failure(task_obj) -> tuple[Optional[str], Optional[str]]:
    """
    Пытаемся достать максимально информативную причину из ответа задач:
    priority: failure_code -> error -> failure_reason -> message
    """
    code = getattr(task_obj, "failure_code", None) or getattr(task_obj, "code", None)
    msg = (
        getattr(task_obj, "error", None)
        or getattr(task_obj, "failure_reason", None)
        or getattr(task_obj, "message", None)
    )
    # часто модерация отдаёт коды вида SAFETY_*
    return (str(code) if code else None, str(msg) if msg else None)


def format_runway_fail_for_user(status: str | None, code: str | None, msg: str | None) -> str:
    # компактная и безопасная нормализация
    status = (status or "FAILED").upper()
    code = (code or "").strip()
    msg  = (msg or "").strip()
    hint = SAFETY_FAILURE_HINTS.get(code, None)
    return hint
    # итоговое текстовое сообщение пользователю
    # parts = [f"Статус: {status}"]
    # if code:
    #     parts.append(f"Код: {code}")
    # if msg:
    #     parts.append(f"Причина: {msg}")
    # if hint:
    #     parts.append(hint)
    # return " | ".join(parts)

# ----------------------- Основная функция генерации -----------------------
async def generate_image_bytes(
    prompt: str,
    images: Optional[Sequence[bytes]] = None,
    *,
    ratio: str = "1920:1080",
    timeout: float = 240.0,
    poll_interval: float = 1.0,
    max_poll_interval: float = 15.0,
    max_retries: int = 3,
) -> bytes:
    from settings import logger
    """
    - Создаёт задачу text_to_image (Gen-4 Image)
    - Поллит её статус до SUCCEEDED/FAILED/timeout
    - При FAILED поднимает RunwayTaskFailed с конкретной причиной
    - Ретраит только 429/сетевые/5xx, как рекомендует Runway
    """
    if ratio not in _ALLOWED_RATIOS:
        logger.warning("Unsupported ratio %s, fallback 1024:1024", ratio)
        ratio = "1024:1024"

    refs = None
    if images:
        refs = [{"uri": _to_data_uri(prepare_ref(b)), "tag": f"ref{i}"} for i, b in enumerate(images)]

    TERMINAL_OK = {"SUCCEEDED"}
    TERMINAL_FAIL = {"FAILED", "CANCELED", "REJECTED"}

    attempt = 0
    while True:
        attempt += 1
        try:
            # 1) Создать задачу
            task = await client.text_to_image.create(
                model="gen4_image",
                ratio=ratio,
                prompt_text=prompt,
                reference_images=refs,
                content_moderation={"publicFigureThreshold": "auto"},
            )
            task_id = task.id
            logger.info("Runway task created: %s", task_id)

            # 2) Ждать завершения (ручной поллинг, т.к. в Python SDK нет wait_for_task_output)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            interval = poll_interval
            last_code: Optional[str] = None
            last_msg: Optional[str] = None

            while True:
                cur = await client.tasks.retrieve(task_id)
                status = (cur.status or "").upper()
                code, msg = _extract_failure(cur)
                if code or msg:
                    last_code, last_msg = code, msg

                if status in TERMINAL_OK:
                    break
                if status in TERMINAL_FAIL:
                    raise RunwayTaskFailed(status=status, code=last_code, message=last_msg)

                if loop.time() > deadline:
                    raise TimeoutError(f"Generation exceeded time limit ({int(timeout)}s)")

                # возможны подсказки по троттлингу внутри metadata
                retry_after = None
                meta = getattr(cur, "metadata", None) or {}
                if isinstance(meta, dict):
                    for key in ("retry_after", "retryAfter", "retryAfterSec",
                                "retry_after_sec", "throttle_seconds", "cooldown"):
                        if key in meta:
                            retry_after = meta[key]
                            break

                if status in {"THROTTLED", "RATE_LIMITED"}:
                    cool = float(retry_after) if retry_after else 18.0
                    cool += random.uniform(0.0, 2.0)
                    await asyncio.sleep(min(cool, max(0.0, deadline - loop.time())))
                    interval = max(poll_interval, min(interval, 2.0))
                else:
                    await asyncio.sleep(min(interval, max(0.0, deadline - loop.time())))
                    interval = min(max_poll_interval, interval * 1.5) + random.uniform(0.0, 0.25)

            # 3) Получить результат и скачать сразу (URL эфемерный)
            if not cur.output or not isinstance(cur.output, (list, tuple)) or not cur.output[0]:
                raise RuntimeError("Empty output from Runway (no URL)")

            url = cur.output[0]
            timeout_dl = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout_dl) as s:
                async with s.get(url) as r:
                    r.raise_for_status()
                    data = await r.read()
            return data

        # ----------------------- Ретраим только то, что имеет смысл -----------------------
        except RateLimitError as e:
            if attempt <= max_retries:
                # экспоненциальный бэкофф с джиттером
                sleep_s = min(60.0, (2 ** attempt) + random.uniform(0, 0.5 * (2 ** attempt)))
                logger.warning("429/Throttle at create: sleep %.1fs (attempt %d/%d)", sleep_s, attempt, max_retries + 1)
                await asyncio.sleep(sleep_s)
                continue
            raise

        except APIConnectionError as e:
            if attempt <= max_retries:
                sleep_s = 1.0 + 0.75 * attempt + random.random()
                logger.warning("APIConnectionError: %s. Retry in %.2fs", e, sleep_s)
                await asyncio.sleep(sleep_s)
                continue
            raise

        except APIStatusError as e:
            logger.log("GPT_ERROR",
                       traceback.format_exc() + '\n\n\n\n' + f'APIStatusError %s:'
                                                                          f' %s{getattr(e, "status_code", "?")}, {getattr(e, "response", None)}')
            # 5xx — можно ретраить; 4xx — обычно ошибка входных данных/модерация и ретрай не поможет
            if getattr(e, "status_code", 0) >= 500 and attempt <= max_retries:
                sleep_s = 1.25 * attempt + random.random()
                await asyncio.sleep(sleep_s)
                continue
            raise

        except RunwayTaskFailed as e:
            human = format_failure_human(e.status, e.code, e.message)
            logger.error("RunwayTaskFailed: %s", human)

            # 1) если хотите возвращать читабельную причину наверх — пробрасываем
            #    то же исключение, но с расширенным сообщением:
            raise RunwayTaskFailed(e.status, e.code, human)
