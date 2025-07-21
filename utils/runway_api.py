import asyncio
import math
import os
import base64
from typing import Sequence, Optional

import aiohttp
from dotenv import load_dotenv, find_dotenv
from runwayml import AsyncRunwayML
from runwayml.types.text_to_image_create_params import ContentModeration

load_dotenv(find_dotenv())
_RW = AsyncRunwayML(api_key=os.getenv("RUNWAY_KEY"))
_HTTP_SESSION: Optional[aiohttp.ClientSession] = None


def _to_data_uri(data: bytes, mime: str = "image/jpeg") -> str:
    """Преобразует байты изображения в data URI."""
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"

async def _session() -> aiohttp.ClientSession:
    global _HTTP_SESSION
    if _HTTP_SESSION is None:
        _HTTP_SESSION = aiohttp.ClientSession()
    return _HTTP_SESSION

from io import BytesIO
from PIL import Image, ImageOps

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


async def generate_image_bytes(
    prompt: str,
    images: Sequence[bytes],
    *,
    ratio: str = "1920:1080",
    poll_interval: float = 1.0,
    timeout: float = 120.0,
) -> bytes:
    refs = [{"uri": _to_data_uri(prepare_ref(img)), "tag": f"ref{i}"} for i, img in enumerate(images)]
    # print(ratio)
    if ratio is None:
        ratio = "1024:1024"
    if ratio not in [
          "1920:1080",
          "1024:1024",
          "1080:1920",
          "1360:768",
          "1080:1080",
          "1168:880",
          "1440:1080",
          "1080:1440",
          "1808:768",
          "2112:912"
        ]:
        ratio = "1024:1024"
    print(ratio)
    task_response = await _RW.text_to_image.create(
        model="gen4_image",
        ratio=ratio,
        prompt_text=prompt,
        reference_images=refs,
        content_moderation={"publicFigureThreshold": "low"}
    )

    task_id = task_response.id
    deadline = asyncio.get_event_loop().time() + timeout

    while True:
        task = await _RW.tasks.retrieve(task_id)
        if task.status in ("SUCCEEDED", "FAILED"):
            break
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError("Generation exceeded time limit")
        await asyncio.sleep(poll_interval)

    if task.status != "SUCCEEDED":
        raise RuntimeError(f"Runway task failed: {task.status}")

    url = task.output[0]  # подписанный URL, действует ≈24 ч.

    async with (await _session()).get(url) as resp:
        resp.raise_for_status()
        return await resp.read()
