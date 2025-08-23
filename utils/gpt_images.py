from __future__ import annotations

import asyncio
import base64
import os
from typing import Any, Awaitable, Callable, Literal

from dotenv import find_dotenv, load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError, )

load_dotenv(find_dotenv())
OPENAI_API_KEY: str | None = os.getenv("GPT_TOKEN") or os.getenv("OPENAI_API_KEY")
DEFAULT_IMAGE_MODEL = "gpt-image-1"
DEFAULT_IMAGE_SIZE = "1024x1024"



UNSUPPORTED_FOR_GPT_IMAGE = {"response_format", "style"}

def _strip_unsupported_params(kwargs: dict) -> dict:
    if (kwargs.get("model") or DEFAULT_IMAGE_MODEL).startswith("gpt-image-1"):
        for p in UNSUPPORTED_FOR_GPT_IMAGE:
            kwargs.pop(p, None)
    return kwargs


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