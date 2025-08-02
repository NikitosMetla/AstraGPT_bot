"""
GPTCompletion — облегчённый аналог utils/combined_gpt_tools.GPT, работающий через Chat
Completions API, а не через Assistants/Threads.

Методы и сигнатуры стараются повторять оригинал, чтобы код бота можно было
переключить на этого клиента без правок.

Ограничения:
• Векторные хранилища и tools не поддерживаются.
• Документы передаются как перечисление имён в тексте.
"""
from __future__ import annotations

import asyncio
import base64
import io
import uuid
from collections import defaultdict
from typing import Any, Sequence, Optional, Dict, List

import aiohttp
import json
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv, find_dotenv
from utils.combined_gpt_tools import dispatch_tool_call
from utils.create_notification import NotificationSchedulerError
from utils.runway_api import generate_image_bytes

load_dotenv(find_dotenv())
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

import aiohttp
from openai import AsyncOpenAI

from settings import get_current_datetime_string, print_log
from db.repository import users_repository

# -------------------------------------------------------------
# Вспомогательные функции
# -------------------------------------------------------------

def _b64(b: bytes) -> str:  # noqa: D401
    """Возвращает Base64-строку изображения."""
    return base64.b64encode(b).decode()


# -------------------------------------------------------------
# Глобальное хранилище сообщений по thread_id
# (в памяти процесса)
# -------------------------------------------------------------
_thread_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
# -------------------------------------------------------------


class GPTCompletion:  # noqa: N801 — имя повторяет оригинальную обёртку
    """Упрощённый клиент Chat Completions с сохранением логики thread."""

    def __init__(self, default_model: str = "gpt-4o-mini", assistant_instructions: str = "") -> None:
        self.default_model = default_model
        self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        self.assistant_instructions = assistant_instructions  # для system prompt

    # ------------------------- tools schemas -------------------------
    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "Search the web for information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "add_notification",
                "description": "Schedule a notification",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "when_send_str": {"type": "string", "description": "When to send (datetime string)"},
                        "text_notification": {"type": "string", "description": "Notification text"}
                    },
                    "required": ["when_send_str", "text_notification"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "generate_image",
                "description": "Generate an image",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Image description"},
                        "n": {"type": "integer", "description": "Number of images", "default": 1},
                        "size": {"type": "string", "description": "Image size", "default": "1024x1024"},
                        "quality": {"type": "string", "description": "Quality", "default": "low"},
                        "edit_existing_photo": {"type": "boolean", "description": "Edit existing photo", "default": False}
                    },
                    "required": ["prompt"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "edit_image_only_with_peoples",
                "description": "Edit image with people",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Edit prompt"},
                        "ratio": {"type": "string", "description": "Aspect ratio"}
                    },
                    "required": ["prompt"]
                }
            }
        }
    ]

    # ------------------------- thread utils -------------------------
    async def _create_thread(self, user_id: int) -> str:
        thread = await self.client.beta.threads.create()
        # Предполагаем, что БД ожидает int — конвертируем str в int (первые цифры)
        thread_id_int = int(thread.id.replace("thread_", "")[:18], 36)  # пример конвертации
        await users_repository.update_thread_id_by_user_id(user_id=user_id, thread_id=thread_id_int)
        return thread.id  # возвращаем str для внутреннего использования

    async def _ensure_thread(self, *, user_id: int, thread_id: str | None) -> str:
        if thread_id is None:
            thread_id = await self._create_thread(user_id)
        return thread_id

    # ------------------------- media helpers ------------------------
    def _image_part(self, img_io: io.BytesIO) -> dict[str, Any]:
        img_io.seek(0)
        b64 = _b64(img_io.read())
        return {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        }

    # --------------------------- main API ---------------------------
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
        user_data: Any | None = None,
    ) -> Any:
        """Отправляет сообщение с поддержкой tools."""
        thread_id = await self._ensure_thread(user_id=user_id, thread_id=thread_id)

        # 1. Добавляем пользовательское сообщение в thread
        from typing import cast

        content, _, _ = await self._build_content(
            text or "",
            image_bytes=image_bytes,
            document_bytes=document_bytes,
            audio_bytes=audio_bytes,
        )
        from openai.types.beta.threads.message_content_part_param import MessageContentPartParam
        content = cast(List[MessageContentPartParam], content)  # type: ignore
        await self.client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=content,
        )

        # 2. Извлекаем последние 10 сообщений
        messages_resp = await self.client.beta.threads.messages.list(thread_id=thread_id, limit=10, order="desc")
        from openai.types.chat import ChatCompletionMessageParam
        history: List[ChatCompletionMessageParam] = []
        for msg in reversed(messages_resp.data):
            content_parts: List[Dict[str, Any]] = []
            for block in msg.content:
                if block.type == "text":
                    content_parts.append({"type": "text", "text": block.text.value})
                elif block.type == "image_file":
                    file_id = block.image_file.file_id
                    file_data = await self.client.files.content(file_id)
                    img_bytes = await file_data.aread()
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{_b64(img_bytes)}"}
                    })
            history.append(cast(ChatCompletionMessageParam, {"role": msg.role, "content": content_parts}))  # type: ignore

        # 3. Системный префикс
        system_prefix = f"Сегодня - {get_current_datetime_string()} по Москве."
        if user_data and getattr(user_data, "context", None):
            system_prefix += "\n\n" + str(user_data.context)
        if not history or history[0].get("role") != "system":
            history.insert(0, {"role": "system", "content": system_prefix + "\n" + self.assistant_instructions})

        # 4. Цикл function calling
        messages = history
        while True:
            response = await self.client.chat.completions.create(
                model=self.default_model,
                messages=messages,
                tools=cast(List[dict[str, Any]], self.TOOLS),  # type: ignore[arg-type]
                tool_choice="auto",
                stream=False,
                timeout=15.0,
            )
            message = response.choices[0].message
            if not message.tool_calls:
                # Нет вызовов — возвращаем текст
                assistant_msg = message.content
                if with_audio_transcription:
                    audio_data = await self.generate_audio_by_text(assistant_msg)
                    return assistant_msg, audio_data
                return assistant_msg

            # Обрабатываем tool calls
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                tool_output = await dispatch_tool_call(tool_call, None, user_id)  # image_client=None, если не нужен
                if isinstance(tool_output, list) and tool_output:  # images
                    return {"text": "Сгенерировал изображение", "images": tool_output}
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": json.dumps({"output": tool_output}),
                })

    async def _build_content(
        self,
        text: str,
        *,
        image_bytes: Sequence[io.BytesIO] | None = None,
        document_bytes: Sequence[tuple[io.BytesIO, str, str]] | None = None,
        audio_bytes: io.BytesIO | None = None,
    ) -> tuple[list[dict], list[dict], list[str]]:
        content: list[dict] = []
        attachments: list[dict] = []
        doc_file_ids: list[str] = []

        if text:
            content.append({"type": "text", "text": text})
        if image_bytes:
            for idx, img_io in enumerate(image_bytes):
                content.append({"type": "image_file", "image_file": {"file_id": f"img_{idx}"}})  # placeholder, реальный file_id не нужен
        if document_bytes:
            text += "\n\nВот названия файлов: " + ", ".join([name for _, name, _ in document_bytes])
            content[0]["text"] = text  # добавляем в текст
        if audio_bytes:
            transcribed = await self.transcribe_audio(audio_bytes)
            content.append({"type": "text", "text": transcribed})
        return content, attachments, doc_file_ids

    # --------------- дополнительные возможности ---------------
    @staticmethod
    async def generate_audio_by_text(text: str) -> io.BytesIO:  # noqa: D401
        """Генерация TTS через /audio/speech (та же логика, что в оригинале)."""
        from settings import OPENAI_API_KEY as _key  # type: ignore
        url = "https://api.openai.com/v1/audio/speech"
        headers = {
            "Authorization": f"Bearer {_key}",
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
            async with session.post(url, headers=headers, json=payload, timeout=30) as resp:  # type: ignore[arg-type]
                if resp.status == 200:
                    return io.BytesIO(await resp.read())
                raise RuntimeError(f"TTS error {resp.status}: {await resp.text()}")

    @staticmethod
    async def transcribe_audio(audio_bytes: io.BytesIO, language: str = "ru") -> str:  # noqa: D401
        from settings import OPENAI_API_KEY as _key  # type: ignore
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {_key}"}
        audio_bytes.name = "audio.mp3"
        data = {"file": audio_bytes, "model": "whisper-1", "language": language}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data, timeout=60) as resp:  # type: ignore[arg-type]
                if resp.status == 200:
                    result = await resp.json()
                    return result.get("text", "")
                raise RuntimeError(f"Whisper error {resp.status}: {await resp.text()}")


# -------------------------------------------------------------
# Экспортируем единый экземпляр (как в original utils.combined_gpt_tools)
# -------------------------------------------------------------
GPT = GPTCompletion  # для совместимости импорта 