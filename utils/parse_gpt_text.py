import re
import html
from aiogram.enums import ParseMode

# ---------------------------------------------------------------------
# Регулярка для HTML-кодовых блоков <pre><code>…</code></pre>
_CODE_BLOCK_RE_HTML = re.compile(
    r"<pre><code(?:\s+class=\"[^\"]*\")?>(.*?)</code></pre>",
    re.DOTALL | re.IGNORECASE
)

# Шаблон для «лишних» Markdown-символов вне кодовых блоков
_MD_SYNTAX_OUTSIDE = re.compile(r"(\*|_|`|~|#{1,6})")

# ---------------------------------------------------------------------
# Преобразование Markdown-блоков ```…``` в HTML <pre><code>…</code></pre>
def _convert_md_to_html_code(text: str) -> str:
    """
    Заменяет все блоки кода в формате Markdown (```…```)
    на HTML-блоки <pre><code>…</code></pre>. Сохраняет язык (если указан),
    экранирует внутри кода символы <, >, &.
    """
    pattern = re.compile(r"```(?:([\w+-]+)\n)?(.*?)```", re.DOTALL)

    def replacer(match: re.Match) -> str:
        lang = match.group(1) or ""
        code_content = match.group(2)
        # Экранируем <, >, & внутри кода, чтобы Telegram отобразил их буквально
        escaped = html.escape(code_content)
        if lang:
            return f"<pre><code class=\"{lang}\">{escaped}</code></pre>"
        else:
            return f"<pre><code>{escaped}</code></pre>"

    return pattern.sub(replacer, text)

# ---------------------------------------------------------------------
def sanitize_html(text: str) -> str:
    """
    1. Сначала преобразует Markdown-блоки ```…``` в
       HTML-блоки <pre><code>…</code></pre>.
    2. Затем экранирует все HTML-«опасные» символы (<, >, &)
       вне блоков <pre><code>…</code></pre>.
    3. Удаляет Markdown-символы (*, _, `, ~, #) вне кодовых блоков.
    В результате текст готов к отправке в Telegram с parse_mode=HTML.
    """
    # 1. Преобразуем Markdown-код в HTML-блоки
    text_with_html_code = _convert_md_to_html_code(text)

    parts = []
    last = 0

    # 2. Проходим по всем уже вставленным HTML-блокам <pre><code>…</code></pre>
    for m in _CODE_BLOCK_RE_HTML.finditer(text_with_html_code):
        # 2a. Текст до текущего блока кода: экранируем HTML и очищаем Markdown-символы
        outside = text_with_html_code[last:m.start()]
        escaped = html.escape(outside)               # Экранируем <, >, & :contentReference[oaicite:3]{index=3}
        cleaned = _MD_SYNTAX_OUTSIDE.sub("", escaped)  # Удаляем *, _, `, ~, # вне кода :contentReference[oaicite:4]{index=4}
        parts.append(cleaned)

        # 2b. Сохраняем сам блок <pre><code>…</code></pre> без изменений
        parts.append(m.group(0))
        last = m.end()

    # 3. Обработка хвоста после последнего блока кода
    outside_tail = text_with_html_code[last:]
    escaped_tail = html.escape(outside_tail)           # Экранируем HTML
    cleaned_tail = _MD_SYNTAX_OUTSIDE.sub("", escaped_tail)  # Удаляем Markdown-символы
    parts.append(cleaned_tail)
    # Собираем всё вместе
    result = "".join(parts).strip()
    return re.sub(r"【[^】]+】", "", result)

# ---------------------------------------------------------------------
# utils/parse_gpt_text.py

import re
from typing import List

def split_telegram_html(text: str, limit: int = 4096) -> List[str]:
    # Разбиваем текст на кодовые блоки и всё остальное
    pattern = re.compile(r'(<pre><code.*?>.*?</code></pre>)', re.DOTALL)
    segments = pattern.split(text)

    parts: List[str] = []
    current = ""

    for seg in segments:
        if not seg:
            continue

        # Если сегмент помещается целиком — просто добавляем
        if len(current) + len(seg) <= limit:
            current += seg
            continue

        # Если сегмент не помещается вместе с current, сбрасываем current
        if current:
            parts.append(current)
            current = ""

        # Если сам сегмент короче лимита — переносим его в current
        if len(seg) <= limit:
            current = seg
            continue

        # А тут сегмент длиннее лимита — разбиваем его отдельно
        if seg.startswith("<pre><code"):
            # Выделяем теги и содержимое
            m = re.match(r'(<pre><code.*?>)(.*?)(</code></pre>)$', seg, re.DOTALL)
            if m:
                open_tag, code_body, close_tag = m.groups()
                lines = code_body.splitlines(keepends=True)
                chunk = ""
                for line in lines:
                    # Если добавление очередной строки превысит лимит — сбрасываем текущий chunk
                    if len(open_tag) + len(chunk) + len(line) + len(close_tag) > limit:
                        parts.append(open_tag + chunk + close_tag)
                        chunk = ""
                    chunk += line
                if chunk:
                    parts.append(open_tag + chunk + close_tag)
                continue

        # Немалый не‑кодовый сегмент: режем по символам
        start = 0
        while start < len(seg):
            end = start + limit
            parts.append(seg[start:end])
            start = end

    # Оставшийся current
    if current:
        parts.append(current)

    return parts


# 1) Markdown [текст](url) → <a href="url" target="_blank">текст</a>
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^\)]+)\)')
def md_to_anchor(text: str) -> str:
    return _MD_LINK_RE.sub(r'<a href="\2" target="_blank">\1</a>', text)

# 2) «Голые» URL → <a href="url" target="_blank">url</a>
_URL_RE = re.compile(r'(?<!["\'=>])(https?://[^\s\)\]]+)')
def url_to_anchor(text: str) -> str:
    return _URL_RE.sub(lambda m: f'<a href="{m.group(1)}" target="_blank">{m.group(1)}</a>', text)

# 3) Плейсхолдеры для уже сгенерированных <a>…</a>
_ANCHOR_RE = re.compile(r'<a href="[^"]+" target="_blank">.*?</a>')
def preserve_anchors(text: str):
    anchors = []
    def _store(m: re.Match) -> str:
        anchors.append(m.group(0))
        return f"@@ANCHOR{len(anchors)-1}@@"
    return _ANCHOR_RE.sub(_store, text), anchors

def restore_anchors(text: str, anchors: list[str]) -> str:
    for i, a in enumerate(anchors):
        text = text.replace(f"@@ANCHOR{i}@@", a)
    return text

# Собираем всё вместе
def sanitize_with_links(raw: str) -> str:
    # а) превращаем Markdown и голые URL в <a>
    t = md_to_anchor(raw)
    t = url_to_anchor(t)

    # б) выносим все <a>…</a> в плейсхолдеры
    t, anchors = preserve_anchors(t)

    # в) чистим остальное привычным sanitize_html
    t = sanitize_html(t)

    # г) возвращаем настоящие теги <a>
    return restore_anchors(t, anchors)





