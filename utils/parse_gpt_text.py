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


# Нормализация &gt; → >
_GT_ENTITY_RE = re.compile(r"&(?:amp;)?gt;")


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
        escaped = html.escape(outside, quote=False)               # Экранируем <, >, & :contentReference[oaicite:3]{index=3}
        cleaned = _MD_SYNTAX_OUTSIDE.sub("", escaped)  # Удаляем *, _, `, ~, # вне кода :contentReference[oaicite:4]{index=4}
        parts.append(cleaned)

        # 2b. Сохраняем сам блок <pre><code>…</code></pre> без изменений
        parts.append(m.group(0))
        last = m.end()

    # 3. Обработка хвоста после последнего блока кода
    outside_tail = text_with_html_code[last:]
    escaped_tail = html.escape(outside_tail, quote=False)          # Экранируем HTML
    cleaned_tail = _MD_SYNTAX_OUTSIDE.sub("", escaped_tail)  # Удаляем Markdown-символы
    parts.append(cleaned_tail)
    # Собираем всё вместе
    # Собираем всё вместе
    result = "".join(parts).strip()

    # <<< ВОТ ДОБАВЛЯЕМ: разворачиваем &gt; обратно в ">"
    result = _GT_ENTITY_RE.sub(">", result)

    return re.sub(r"【[^】]+】", "", result)


# ---------------------------------------------------------------------
# utils/parse_gpt_text.py

import re
from typing import List

def split_telegram_html(text: str, limit: int = 4096) -> List[str]:
    """
    Режем HTML-текст под Telegram (HTML parse_mode), не ломая теги:
    - кодовые блоки <pre><code...>...</code></pre> — уже были поддержаны;
    - ссылки <a href="...">...</a> теперь тоже атомарны; если одна ссылка длиннее limit,
      раскалываем её содержимое, закрывая/открывая тег на границах чанков.
    """
    # 1) Сначала выделяем как отдельные сегменты КОД и ССЫЛКИ
    pattern = re.compile(r'(<pre><code.*?>.*?</code></pre>|<a href="[^"]+">.*?</a>)',
                         re.DOTALL | re.IGNORECASE)
    segments = pattern.split(text)

    parts: List[str] = []
    current = ""

    def flush_current():
        nonlocal current
        if current:
            parts.append(current)
            current = ""

    for seg in segments:
        if not seg:
            continue

        seg_len = len(seg)

        # Если целиком помещается вместе с текущим — добавляем
        if len(current) + seg_len <= limit:
            current += seg
            continue

        # Если текущий буфер непустой — сбрасываем перед обработкой большого сегмента
        flush_current()

        # Если сам сегмент помещается в пустой — просто положим
        if seg_len <= limit:
            current = seg
            continue

        # 2) Сегмент длиннее лимита — это либо кодовый блок, либо <a>
        if seg.startswith("<pre><code"):
            # Разбиваем содержимое построчно, КАЖДЫЙ чанк оборачиваем в open/close
            m = re.match(r'(<pre><code.*?>)(.*?)(</code></pre>)$', seg, re.DOTALL | re.IGNORECASE)
            if m:
                open_tag, code_body, close_tag = m.groups()
                lines = code_body.splitlines(keepends=True)

                chunk = ""
                for line in lines:
                    if len(open_tag) + len(chunk) + len(line) + len(close_tag) > limit:
                        parts.append(open_tag + chunk + close_tag)
                        chunk = ""
                    chunk += line
                if chunk:
                    parts.append(open_tag + chunk + close_tag)
                continue  # к следующему сегменту

        if seg.startswith("<a href="):
            # Разбиваем якорь, сохраняя <a>…</a> вокруг каждого чанка
            m = re.match(r'(<a href="[^"]+">)(.*?)(</a>)$', seg, re.DOTALL | re.IGNORECASE)
            if m:
                open_tag, body, close_tag = m.groups()
                inner_limit = limit - len(open_tag) - len(close_tag)
                if inner_limit <= 0:
                    # Совсем экзотика: если даже пустая пара тегов не влезает,
                    # рвём тело ссылки как текст без тега
                    start = 0
                    while start < len(body):
                        end = start + limit
                        parts.append(body[start:end])
                        start = end
                    continue

                # Чанкуем тело ссылки по символам (без потери тегов)
                start = 0
                while start < len(body):
                    end = min(start + inner_limit, len(body))
                    chunk_body = body[start:end]
                    parts.append(open_tag + chunk_body + close_tag)
                    start = end
                continue  # к следующему сегменту

        # 3) Иной большой сегмент (обычный текст) — режем по символам
        start = 0
        while start < seg_len:
            end = start + limit
            parts.append(seg[start:end])
            start = end

    # Хвост
    flush_current()
    return parts



# 1) Markdown [текст](url) → <a href="url">текст</a>  (БЕЗ target)
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^\)]+)\)')
def md_to_anchor(text: str) -> str:
    return _MD_LINK_RE.sub(r'<a href="\2">\1</a>', text)

# 2) «Голые» URL → <a href="url">url</a>  (БЕЗ target)
_URL_RE = re.compile(r'(?<!["\'=>])(https?://[^\s\)\]]+)')
def url_to_anchor(text: str) -> str:
    return _URL_RE.sub(lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', text)

# 3) Плейсхолдеры для уже сгенерированных <a>…</a> (без target)
_ANCHOR_RE = re.compile(r'<a href="[^"]+">.*?</a>', re.DOTALL | re.IGNORECASE)
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
def sanitize_with_links(raw: str | None = None) -> str:
    if raw is None:
        return ""
    t = md_to_anchor(raw)
    t = url_to_anchor(t)
    t, anchors = preserve_anchors(t)
    t = sanitize_html(t)
    t = restore_anchors(t, anchors)
    # жёсткая зачистка запрещённых атрибутов у <a>
    t = re.sub(r'\s+target="_blank"', "", t, flags=re.IGNORECASE)
    return t






