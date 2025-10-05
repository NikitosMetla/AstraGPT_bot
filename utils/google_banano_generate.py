from __future__ import annotations
import os
import asyncio
from io import BytesIO
from typing import Optional, Sequence, Union, List, Tuple
from PIL import Image
from dotenv import load_dotenv, find_dotenv
from google import genai
from google.genai import types, errors


class GeminiImageError(Exception):
    pass


class InvalidPromptError(GeminiImageError):
    pass


class AuthError(GeminiImageError):
    pass


class RateLimitError(GeminiImageError):
    pass


class TransientError(GeminiImageError):
    pass


class SafetyBlockedError(GeminiImageError):
    pass


class NoImageInResponseError(GeminiImageError):
    pass


class PromptBlockedError(GeminiImageError):
    def __init__(self, reason: str):
        super().__init__(f"Промпт заблокирован политиками безопасности: {reason}")
        self.reason = reason

class ResponseBlockedError(GeminiImageError):
    def __init__(self, finish_reason: str, safety: list | None = None):
        msg = f"Ответ заблокирован (finish_reason={finish_reason})"
        if safety:
            cats = ", ".join(f"{r.category}:{r.probability}" for r in safety if hasattr(r, "category"))
            msg += f"; safety_ratings=[{cats}]"
        super().__init__(msg)
        self.finish_reason = finish_reason
        self.safety = safety or []


class TextRefusalError(GeminiImageError):
    def __init__(self, text: str, safety: list | None = None):
        msg = f"Модель вернула текстовый отказ без изображения: {text[:200]}..."
        if safety:
            cats = ", ".join(f"{r.category}:{r.probability}" for r in safety if hasattr(r, "category"))
            msg += f" | safety_ratings=[{cats}]"
        super().__init__(msg)
        self.text = text
        self.safety = safety or []




class GeminiImageService:
    """
    Класс-обёртка: один экземпляр -> один реиспользуемый genai.Client.
    Вся остальная логика оставлена неизменной.
    """

    _MIME_BY_FORMAT = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "JPG": "image/jpeg",
        "WEBP": "image/webp",
    }

    def __init__(self, api_key: Optional[str] = None, *, timeout: float = 60.0):
        load_dotenv(find_dotenv())
        key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not key:
            raise AuthError("Не задан API-ключ (GOOGLE_API_KEY / GEMINI_API_KEY или параметр api_key).")
        # В SDK таймаут ожидается в миллисекундах
        self._client = genai.Client(
            api_key=key,
            http_options=types.HttpOptions(timeout=int(timeout * 1000))
        )

    # --- Вспомогательные методы (идентичная логика, перенесены внутрь класса) ---

    @staticmethod
    def _detect_or_convert_to_png(img_bytes: bytes) -> Tuple[str, bytes]:
        try:
            with Image.open(BytesIO(img_bytes)) as im:
                fmt = (im.format or "PNG").upper()
                if fmt in GeminiImageService._MIME_BY_FORMAT:
                    return GeminiImageService._MIME_BY_FORMAT[fmt], img_bytes
                out = BytesIO()
                im.save(out, format="PNG")
                return "image/png", out.getvalue()
        except Exception as e:
            raise GeminiImageError(f"Невозможно прочитать входное изображение: {e}") from e

    @staticmethod
    def _normalize_ref_images(reference_images: Optional[Union[bytes, Sequence[bytes]]]) -> List[bytes]:
        if reference_images is None:
            return []
        if isinstance(reference_images, (bytes, bytearray)):
            return [bytes(reference_images)]
        return [bytes(b) for b in reference_images]

    @classmethod
    def _build_contents(cls, prompt: str, ref_imgs: List[bytes]) -> List[Union[str, types.Part]]:
        parts: List[Union[str, types.Part]] = [prompt]
        for b in ref_imgs:
            mime, raw = cls._detect_or_convert_to_png(b)
            parts.append(types.Part.from_bytes(data=raw, mime_type=mime))
        return parts

    @staticmethod
    def _extract_first_image_bytes(response) -> bytes:
        # 1) Блок промпта
        fb = getattr(response, "prompt_feedback", None) or getattr(response, "promptFeedback", None)
        if fb and getattr(fb, "block_reason", None):
            raise PromptBlockedError(str(fb.block_reason))

        # 2) Кандидаты
        try:
            cand0 = response.candidates[0]
        except IndexError:
            # промпт заблокирован или иная ситуация без кандидатов
            raise NoImageInResponseError("Кандидаты отсутствуют (возможна блокировка промпта).")

        finish_reason = getattr(cand0, "finish_reason", None)
        safety = getattr(cand0, "safety_ratings", None) or getattr(cand0, "safetyRatings", None)

        # 3) Если явная блокировка ответа
        if finish_reason and str(finish_reason).upper() == "SAFETY":
            raise ResponseBlockedError("SAFETY", safety)

        content = getattr(cand0, "content", None)
        parts = getattr(content, "parts", None) if content else None
        if parts:
            # 3.1) сначала ищем картинку inline_data
            for p in parts:
                if getattr(p, "inline_data", None) and getattr(p.inline_data, "data", None):
                    return p.inline_data.data
            # 3.2) возможный будущий формат: file_data (ссылка на файл из File API)
            for p in parts:
                file_data = getattr(p, "file_data", None) or getattr(p, "fileData", None)
                if file_data and getattr(file_data, "file_uri", None):
                    # тут можно либо скачать, либо пробросить ссылку выше в виде исключения с контекстом
                    raise NoImageInResponseError(f"Изображение выдано как file_data: {file_data.file_uri}")

            # 3.3) если части есть, но это текст (отказ/предупреждение), поднимем TextRefusalError
            texts = []
            for p in parts:
                if hasattr(p, "text") and isinstance(p.text, str) and p.text.strip():
                    texts.append(p.text.strip())
            if texts:
                raise TextRefusalError(" ".join(texts), safety)

        # 4) Ничего пригодного не нашли
        raise NoImageInResponseError("В ответе отсутствуют данные изображения (inline_data/file_data).")

    # --- Публичный метод с прежней логикой (кроме создания клиента) ---

    async def generate_gemini_image(
        self,
        prompt: str,
        reference_images: Optional[Union[bytes, Sequence[bytes]]] = None,
        *,
        api_key: Optional[str] = None,  # сохранён для совместимости, но НЕ используется (клиент уже создан)
        model: str = "gemini-2.5-flash-image-preview",
        timeout: float = 60.0,          # сохранён для совместимости; фактический таймаут задан в __init__
        max_retries: int = 2,
    ) -> bytes:
        if not isinstance(prompt, str) or not prompt.strip():
            raise InvalidPromptError("Параметр 'prompt' обязателен и не должен быть пустым.")

        refs = self._normalize_ref_images(reference_images)
        contents = self._build_contents(prompt, refs)

        attempt = 0
        while True:
            try:
                response = await self._client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                )
                return self._extract_first_image_bytes(response)

            except PromptBlockedError as e:
                raise

            except ResponseBlockedError as e:
                raise
            except TextRefusalError as e:
                raise  # или тут же маппинг на «смягчённый» ретрай — см. ниже

            except errors.APIError as e:
                code = getattr(e, "code", None)
                msg = getattr(e, "message", str(e))
                if code in (401, 403):
                    raise AuthError(f"Ошибка авторизации ({code}): {msg}") from e
                if code == 429:
                    if attempt < max_retries:
                        attempt += 1
                        await asyncio.sleep(min(2 ** attempt, 8))
                        continue
                    raise RateLimitError(f"Превышен лимит запросов (429): {msg}") from e
                if code in (500, 502, 503, 504):
                    if attempt < max_retries:
                        attempt += 1
                        await asyncio.sleep(min(2 ** attempt, 8))
                        continue
                    raise TransientError(f"Временная ошибка сервера ({code}): {msg}") from e
                raise GeminiImageError(f"APIError {code}: {msg}") from e

            except (SafetyBlockedError, NoImageInResponseError):
                raise

            except Exception as e:
                raise GeminiImageError(f"Низкоуровневая ошибка: {e}") from e
