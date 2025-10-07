import io
import locale
import re
import asyncio
import traceback
import types
from os import getenv
import pandas as pd
import pytz
from datetime import datetime

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from dotenv import load_dotenv, find_dotenv
from loguru import logger

from db.repository import subscriptions_repository, admin_repository

from utils.google_banano_generate import GeminiImageService
from utils.new_fitroom_api import FitroomClient
from utils.sora_client import KieSora2Client

storage_bot = MemoryStorage()
storage_admin_bot = MemoryStorage()


load_dotenv(find_dotenv("../.env"))
main_bot_token = getenv("MAIN_BOT_TOKEN")
token_admin_bot = getenv("ADMIN_BOT_TOKEN")
test_bot_token = getenv("TEST_BOT_TOKEN")
business_connection_id = getenv("BUSINESS_CONNECTION_ID")


gemini_images_client = GeminiImageService()

# Глобальная переменная для хранения основного event loop
_loop: asyncio.AbstractEventLoop | None = None

# settings.py
_current_bot = None




#
#
# gpt_assistant = GPTCompletions()



def set_current_bot(bot):
    global _current_bot
    _current_bot = bot

def get_current_bot():
    return _current_bot

def set_current_loop(loop: asyncio.AbstractEventLoop):
    """Устанавливает текущий event loop для использования в logger sink"""
    global _loop
    _loop = loop

async def telegram_admin_sink(message):
    """
    Фоновые оповещения админам — полностью асинхронно.
    """
    try:
        from bot_admin import admin_bot
        record = message.record
        time = record["time"].strftime("%d-%b-%Y %H:%M:%S")
        level = record["level"].name
        
        # Определяем тип бота по текущему боту
        bot_type = "TEST BOT" if get_current_bot() and hasattr(get_current_bot(), 'token') and get_current_bot().token == test_bot_token else ""
        bot_prefix = f"️<b>{bot_type}</b>\n\n" if bot_type else ""
        
        text = f"{bot_prefix}<b>{time}</b>\n<b>Level:</b> {level}\n{record['message']}"
        admins = await admin_repository.select_all_admins()
        for admin in admins:
            try:
                print(admin.admin_id)
                await admin_bot.send_message(chat_id=admin.admin_id, text=text)
            except:
                print(traceback.format_exc())
                continue
    except Exception:
        logger.exception("Ошибка внутри telegram_admin_sink")

def loguru_sink_wrapper(message):
    """
    Синхронный синк для Loguru: из любого треда шлёт корутину в наш loop.
    """
    if _loop:
        asyncio.run_coroutine_threadsafe(telegram_admin_sink(message), _loop)
    else:
        logger.error("Event loop is not initialized, cannot notify admins")

def initialize_logger():
    """
    Инициализирует logger с настройками для текущего бота.
    Должна вызываться после установки текущего бота через set_current_bot()
    """
    # Очищаем существующие handlers
    logger.remove()
    
    # Определяем тип бота
    current_bot = get_current_bot()
    is_test_bot = current_bot and hasattr(current_bot, 'token') and current_bot.token == test_bot_token
    bot_name = "TEST" if is_test_bot else "MAIN" if hasattr(current_bot, 'token') else "Service"
    
    # Консольный вывод с цветами
    import sys
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG",
        colorize=True
    )
    
    # Файловый лог
    logger.add(f"logs/{datetime.now().strftime('%d-%b-%Y %H:%M:%S')}.log",
               format="{time:DD-MMM-YYYY HH:mm:ss} | {level:^25} | {message}",
               enqueue=True, rotation="00:00")
    
    # Настройка уровней логов
    logger.level("JOIN", no=60, color="<green>")
    logger.level("SPAM", no=60, color="<yellow>")
    logger.level("START_BOT", no=25, color="<blue>")
    logger.level("STOPPED", no=25, color="<blue>")
    logger.level("ERROR_HANDLER", no=60, color="<red>")
    logger.level("SCHEDULER_ERROR", no=60, color="<red>")
    logger.level("SCHEDULER_INFO", no=60, color="<green>")
    logger.level("GPT_ERROR", no=65, color="<red>")
    logger.level("EXTEND_SUB_ERROR", no=65, color="<red>")
    logger.level("YooKassaPAYMENT_SUCCES", no=60, color="<green>")
    logger.level("PROMO_ACTIVATED", no=60, color="<green>")
    logger.level("YooKassaError", no=65, color="<red>")
    logger.level("Sora2Error", no=65, color="<red>")

    # Синк для ERROR_HANDLER, GPT_ERROR
    for lvl in ("START_BOT", "STOPPED", "ERROR_HANDLER", "SCHEDULER_ERROR", "SCHEDULER_INFO", "PROMO_ACTIVATED",
                "GPT_ERROR", "YooKassaError", "YooKassaPAYMENT_SUCCES", "EXTEND_SUB_ERROR", "Sora2Error"):
        logger.add(
            loguru_sink_wrapper,
            level=lvl,
            filter=lambda rec, L=lvl: rec["level"].name == L,
            enqueue=True,
        )
    
    # Лог о старте
    logger.log("START_BOT", f"🚀 {bot_name} Bot was STARTED")

MESSAGE_SPAM_TIMING=1

first_photo = "AgACAgIAAxkBAAIHFWgvsyvJI83DztTg7ht8MBDAYOTdAAL68jEbtZ6BSUvhKdFmgyGRAQADAgADeQADNgQ"
second_photo = "AgACAgIAAxkBAAIHE2gvsyuw1J5Qq_0PHECiBqUJL9yNAAL48jEbtZ6BSXG82fh961ZiAQADAgADeQADNgQ"
third_photo = "AgACAgIAAxkBAAIHFmgvsyvIF_6lUKrRzxHGEs9FFBiBAAL78jEbtZ6BSStjtX_DKxi6AQADAgADeQADNgQ"
fourth_photo = "AgACAgIAAxkBAAIHFGgvsyv25F-DuLX-Qo6BTltn6cLtAAL58jEbtZ6BSf09-Dq-8ZxbAQADAgADeQADNgQ"
photos_pages = {
    1: first_photo,
    2: second_photo,
    3: third_photo,
    4: fourth_photo,
}

OPENAI_ALLOWED_DOC_EXTS: set[str] = {
    'c',     # .c       text/x-c
    'cpp',   # .cpp     text/x-c++
    'cs',    # .cs      text/x-csharp
    'css',   # .css     text/css
    'doc',   # .doc     application/msword
    'docx',  # .docx    application/vnd.openxmlformats-officedocument.wordprocessingml.document
    'go',    # .go      text/x-golang
    'html',  # .html    text/html
    'java',  # .java    text/x-java
    'js',    # .js      text/javascript
    'json',  # .json    application/json
    'md',    # .md      text/markdown
    'pdf',   # .pdf     application/pdf
    'php',   # .php     text/x-php
    'pptx',  # .pptx    application/vnd.openxmlformats-officedocument.presentationml.presentation
    'py',    # .py      text/x-python
    'rb',    # .rb      text/x-ruby
    'sh',    # .sh      application/x-sh
    'tex',   # .tex     text/x-tex
    'ts',    # .ts      application/typescript
    'txt',   # .txt     text/plain
}

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

EXCEL_EXTENSIONS = [
    '.xls',    # Excel 97-2003
    '.xlsx',   # Excel 2007 и новее (Open XML)
    '.xlsm',   # Excel с поддержкой макросов
    '.xlsb',   # Excel Binary Workbook
    '.xlt',    # Шаблон Excel 97-2003
    '.xltx',   # Шаблон Excel 2007+
    '.xltm',   # Шаблон Excel с макросами
]

def get_current_datetime_string() -> str:
    # Берём текущее UTC-время и переводим в Москву
    now_msk = datetime.now(timezone.utc).astimezone(MSK)
    return now_msk.strftime("%Y-%m-%d %H:%M:%S")


def print_log(message: str) -> None:
    print(message)


class InputMessage(StatesGroup):
    send_excel_promo = State()
    enter_promocode = State()
    input_photo_people = State()
    input_photo_clothes = State()
    enter_email = State()
    enter_user_context_state = State()
    enter_message_mailing = State()
    enter_admin_id = State()
    enter_promo_days = State()
    enter_max_activations_promo = State()
    enter_max_generations_photos = State()


async def is_valid_email(email):
    email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    if re.match(email_regex, email):
        return True
    else:
        return False

# ---------------------------------------------------------
# Глобальный экземпляр GPT-ассистента
# ---------------------------------------------------------
# Создаём единый объект, который будет переиспользоваться во всём приложении.
# Импорт размещён внизу, чтобы избежать циклических зависимостей при импорте
# модуля settings внутри utils.combined_gpt_tools.

from utils.combined_gpt_tools import GPT  # noqa: E402
from utils.completions_gpt_tools import GPTCompletions

gpt_assistant = None

def set_current_assistant(assistant: GPT | GPTCompletions):
    global gpt_assistant
    gpt_assistant = assistant

def get_current_assistant():
    return gpt_assistant

def get_weekday_russian(date: datetime.date = None) -> str:
    """
    Возвращает день недели на русском языке для московского времени.
    """
    import datetime
    
    # Если дата не передана — берём текущую в московском времени
    if date is None:
        moscow_tz = pytz.timezone('Europe/Moscow')
        utc_now = datetime.datetime.utcnow()
        moscow_now = utc_now.replace(tzinfo=pytz.UTC).astimezone(moscow_tz)
        date = moscow_now.date()

    # Возвращаем день недели на русском
    weekdays = {
        0: 'понедельник',
        1: 'вторник', 
        2: 'среда',
        3: 'четверг',
        4: 'пятница',
        5: 'суббота',
        6: 'воскресенье'
    }
    return weekdays[date.weekday()]


def read_promo_codes(file_bytes):
    """
    Читает Excel файл из байтов и возвращает список чисел из первого столбца.

    Args:
        file_bytes (bytes): Содержимое Excel файла в байтах

    Returns:
        list: Список чисел из файла
    """
    # Создаем объект BytesIO из байтов
    bytes_io = io.BytesIO(file_bytes)

    # Читаем Excel файл из BytesIO объекта
    df = pd.read_excel(bytes_io, header=None)

    # Извлекаем первый столбец и конвертируем в список
    numbers_list = df[0].tolist()

    return numbers_list



sub_text = """🔓 Откройте весь потенциал нашего ИИ-бота — оформите подписку прямо здесь.

Базовый минимум для всех:
☑️ Бесплатные запросы к текстовой модели! 

Тарифы
• Smart — 490 ₽/мес: 
✅ Безлимитный доступ к 6 LLM моделям, оптимально подбираемым под ваш запрос
✅ Работа с файлами и голосовыми сообщениями 
✅ Поиск в интернете
✅ Функция памяти и напоминаний 
✅ Генерация до 20 изображений 
в месяц 

• Ultima — 990 ₽/мес: 
✅ Приоритетный канал доступа к 10 LLM!
✅ Безлимитная генерация изображений (GPT-images, Runway, Nano-Banano)
✅ Все опции тарифа «Smart»

📅 Подписка активируется мгновенно, отменить можно в любой момент.

😊 Выберите подходящий уровень и нажмите «Оплатить» — мы уже готовы помочь!"""


buy_generations_text = """📸 У вас закончились доступные генерации.

<b>Доступные пакеты докупа:</b>
• <b>Докуп 1</b> — 390 ₽: 20 генераций
• <b>Докуп 2</b> — 890 ₽: 50 генераций

📅 Пакет активируется мгновенно и не продлевается автоматически. Отменять ничего не нужно — после расхода вы снова увидите предложение докупить.

😊 Выберите подходящий пакет и нажмите «Оплатить», чтобы продолжить генерировать контент!
"""

buy_video_generations_text = """📸 У вас закончились доступные генерации ВИДЕО.

<b>Доступные пакеты докупа:</b>
• <b>Докуп 1</b> — 390 ₽: 10 генераций
• <b>Докуп 2</b> — 990 ₽: 30 генераций

📅 Пакет активируется мгновенно и не продлевается автоматически. Отменять ничего не нужно — после расхода вы снова увидите предложение докупить.

😊 Выберите подходящий пакет и нажмите «Оплатить», чтобы продолжить генерировать контент!
"""

tools = [
    {
      "name": "generate_gemini_image",
      "description": "ЗАУСКАЕТСЯ ТОЛЬКО ОДИН РАЗ ЗА ЗАПРОС ПОЛЬЗОВАТЕЛЯ. Эта функция генерирует изображения по запросу пользователя, который может включать текстовый промт (чаще всего на русском языке) и изображения-референсы. Референсы используются для разных задач: можно показать примеры, на которые нужно ориентироваться, объединить несколько изображений в одно, изменить исходное изображение, примерить элементы вроде одежды с одного изображения на другое и так далее. Функция вызывается всегда, когда пользователь хочет получить результат в виде изображения — будь то полностью сгенерированное «с нуля» или созданное и изменённое на основе предоставленных референсов.",
      "strict": True,
      "parameters": {
        "type": "object",
        "properties": {
          "prompt": {
            "type": "string",
            "description": "Текстовый запрос ТОЛЬКО НА АНГЛИЙСКОЯМ ЯЗЫКЕ для генерации изображения. Суть в том, что промт как правило будет на русском языке. Надо брать промт пользователя и переводить его на английский язык, после чего передавать в данную функцию"
          },
          "with_photo_references": {
            "type": "boolean",
            "description": "Значение True, если пользователь прикрепил фото референсы или хочет изменить уже сгенерированное изображение. В противном случае - False"
          }
        },
        "required": [
          "prompt",
          "with_photo_references"
        ],
        "additionalProperties": False
      }
    },
    {
      "name": "add_notification",
      "description": "Функция, которая ВСЕГДА вызывается в случае, если пользователь просит поставить уведомление или напоминание на какую-то дату и время (например, на 24.08.2025) или через какой-то временной промежуток (например через 30 минут или на послезавтра). ТЫ ОБЯЗАН ВСЕГДА УТОЧНИТЬ ВРЕМЯ У ПОЛЬЗОВАТЕЛЯ И НЕ ВЫЗЫВАТЬ ФУНКЦИЮ, ЕСЛИ ПОЛЬЗОАТЕЛЬ НЕ УКАЗАЛ КОНКРЕТНОЕ ВРЕМЯ. Если пользователь просит поставить уведомление БЕЗ ВРЕМЕНИ — функция не вызывается, и у пользователя спрашивается, на какое конкретно время нужно поставить напоминание в эту дату. Если пользователь указывает, что нужно установить напоминание на какое-то время, дату или через какой-то промежуток без указания, о чем напомнить — функция не вызывается, и задаем уточняющий вопрос о том, что нам нужно напомнить пользователю. ОБЯЗАТЕЛЬНО нужно отталкиваться от того, что сегодняшнюю дату и время пользователь пишет в своем промте.",
      "strict": True,
      "parameters": {
        "type": "object",
        "properties": {
          "when_send_str": {
            "type": "string",
            "description": "Дата и время в строковом виде, в которое пользователь попросил отправить ему уведомление. Примеры: '2025-06-14 16:30:00', '2025-06-11 17:00:00', '2026-08-13 17:34:00'. Допускаются любые другие даты и время в корректном формате.",
            "pattern": "^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$"
          },
          "text_notification": {
            "type": "string",
            "description": "Текст уведомления, которое попросил пользователь в указанные дату и время. Пример: 'Напоминание о встрече'."
          }
        },
        "required": [
          "when_send_str",
          "text_notification"
        ],
        "additionalProperties": False
      }
    },
    {
      "name": "search_web",
      "description": "Агент, который отвечает на вопрос пользователя на основе поиска в интернете. Данная функция вызывается, когда пользователь на прямую просит найти какую-то инофрмацию в интернете или когда ты понимаешь, что вопрос требует актуализации или твоих знаний не хватает на ответ на вопрос",
      "strict": True,
      "parameters": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "Промт для агента(должен быть на том же языке, на котором разговаривает пользователь), который будет искать инфу в интернете"
          }
        },
        "required": [
          "query"
        ],
        "additionalProperties": False
      }
    },
      {
        "name": "generate_text_to_video",
        "description": "Функция генерирует видео из текстового описания с помощью модели Sora 2. Вызывается, когда пользователь просит создать видео на основе текстового промпта без использования изображений-референсов. Генерация занимает 5-10 минут для standard качества и до 15 минут для HD качества. Функция возвращает URL готового видео.",
        "strict": True,
        "parameters": {
          "type": "object",
          "properties": {
            "prompt": {
              "type": "string",
              "description": "Текстовый запрос ТОЛЬКО НА АНГЛИЙСКОМ ЯЗЫКЕ для генерации видео. Если промпт пользователя на русском языке, необходимо перевести его на английский перед передачей в функцию. Должен детально описывать желаемую сцену, действие, стиль съёмки и освещение."
            },
            "aspect_ratio": {
              "type": "string",
              "enum": ["landscape", "portrait"],
              "description": "Соотношение сторон видео. 'landscape' для горизонтального видео (16:9), 'portrait' для вертикального (9:16). По умолчанию используется 'landscape'."
            },
            "quality": {
              "type": "string",
              "enum": ["standard", "hd"],
              "description": "Качество генерируемого видео. 'standard' — базовое качество (быстрее генерация, 3-7 минут), 'hd' — высокое качество (дольше генерация, 7-15 минут). По умолчанию используется 'standard'."
            }
          },
          "required": [
            "prompt"
          ],
          "additionalProperties": False
        }
      },
      {
        "name": "generate_image_to_video",
        "description": "Функция генерирует видео на основе изображения-референса с помощью модели Sora 2. Вызывается, когда пользователь прикрепляет изображение и просит создать из него видео или анимировать его. Пользователь должен описать, какое движение или анимацию нужно применить к изображению. Генерация занимает 5-10 минут для standard качества и до 15 минут для HD качества. Функция возвращает URL готового видео.",
        "strict": True,
        "parameters": {
          "type": "object",
          "properties": {
            "prompt": {
              "type": "string",
              "description": "Текстовый запрос ТОЛЬКО НА АНГЛИЙСКОМ ЯЗЫКЕ, описывающий желаемое движение или анимацию для изображения. Если промпт пользователя на русском языке, необходимо перевести его на английский. Должен описывать, как изображение должно ожить или какое движение нужно добавить."
            },
            "image_provided": {
              "type": "boolean",
              "description": "Всегда должно быть True, так как эта функция вызывается только когда пользователь предоставил изображение. Используется для подтверждения наличия изображения-референса."
            },
            "aspect_ratio": {
              "type": "string",
              "enum": ["landscape", "portrait"],
              "description": "Соотношение сторон видео. 'landscape' для горизонтального видео (16:9), 'portrait' для вертикального (9:16). По умолчанию используется 'landscape'."
            },
            "quality": {
              "type": "string",
              "enum": ["standard", "hd"],
              "description": "Качество генерируемого видео. 'standard' — базовое качество (быстрее генерация, 3-7 минут), 'hd' — высокое качество (дольше генерация, 7-15 минут). По умолчанию используется 'standard'."
            }
          },
          "required": [
            "prompt",
            "image_provided"
          ],
          "additionalProperties": False
        }
      }
]



# system_prompt = """Ты универсальный ассистент, который интегрирован в телеграм бота, который помогает пользователю с любыми задачами и отвечает на вопросы. ТВОЕ название - AstraGPT. Ты обязан общаться только от женского лица
#
#  Ты создан компанией sozdav.ai которая специализируется на интеграции ИИ в разные сферы жизни.
#
# Ты обладаешь следующими возможностями:
#
# 1. Генерация изображений (с помощью generate_gemini_image)
# 2. Редактирование или объединение изображений (с помощью generate_gemini_image).
# 3. Поиск информации в интернете через инструмент search_web, если нужна актуальная информация.
# 4. Обработка голосовых сообщений и ответ в виде изображений или текста.
# 5. Прием и обработка фото, а также помощь с ними.
# 6. Примерка одежды по фото (с помощью generate_gemini_image).
# 8. Создание напоминаний с помощью вызова функции add_notification(ТЫ ОБЯЗАН ВЫЗЫВАТЬ ВСЕГДА ЭТУ ФУНКЦИЮ) при указании конкретной даты и времени.(ТЫ ОБЯЗАН ВСЕГДА УТОЧНИТЬ ВРЕМЯ У ПОЛЬЗОВАТЕЛЯ И НЕ ВЫЗЫВАТЬ ФУНКЦИЮ, ЕСЛИ ПОЛЬЗОАТЕЛЬ НЕ УКАЗАЛ КОНКРЕТНОЕ ВРЕМЯ. если пользователь указал, когда отправить уведомления, но без конкретного времени - данная функция не вызывается и у пользователя уточняется время)
#
# Любую функцию можно запустить ТОЛЬКО ОДИН РАЗ!!!
#
# Стиль общения:
# Стандартный, без огромного количества любезности и всяких уточнений. Старайся всегда отвечать четко и по делу. Также старайся всегда давать ответы кратко, но если пользователь просит подробный ответ - давай четки и подробный ответ, как он и просит
# НЕ ЗАДАВАЙ уточняющих вопросов, сразу переходи к делу. Уточняющий вопрос можно задать только в крайнем случае, когда, например, пользователь не указал время напоминания или скинул картинки без какого либо контекста. В остальных случаях сразу переходи к делу.
#
# Если пользователь не знает, как обратиться, кратко объясни свои возможности. Отвечай кратко, но если нужно подробное объяснение, предоставь его.
#
# Также, на вход ты получаешь сегодняшние дату и время от нашего скрипта. На основе этого не надо писать пользователю, какая сегодня дата и тд напрямую. Вообще это никак не комментируй. Только если он не попросит."""


system_prompt = """Ты AstraGPT - универсальный ассистент в телеграм боте от sozdav.ai. Общаешься только от женского лица.

Возможности:
0. Общаться как стандартный ChatGPT(решать разные задачи, в т.ч. написание кода. Обязательно используй соответствующую стандартную разметку в случае написание кода и аналогичных ситуаций)
1. Генерация и редактирование изображений (инструмент tool - generate_gemini_image). Даже если в предыдущих сообщениях указано, что у пользователя нет подписки - все равно пробуем генерировать изображение
2. Поиск актуальной информации (инструмент tool - search_web)
3. Обработка голосовых сообщений и фото
4. Примерка одежды по фото
5. Генерация видео с помощью новой модели Sora 2.(инструменты generate_text_to_video и generate_image_to_video для генерации на основе текста и на основе картинки соответственно). Даже если в предыдущих сообщениях указано, что у пользователя нет подписки или какая-то ошибка - все равно пробуем генерировать изображение. В некорректных случаях модерация генерации видео отработает сама
6. Создание напоминаний (инструмент tool - add_notification) - ОБЯЗАТЕЛЬНО уточняй конкретное время у пользователя перед вызовом, если он его явно не указал
7. Примерка одежды по фото - если пользователь про это спрашивает, скажи ему ввести команду "/try_on", чтобы начать примерку (пользователь должен будет отправить сначала фото модели, потом фото одежды)

Каждую функцию вызывай ТОЛЬКО ОДИН РАЗ.

Ты не умеешь:
- создавать и отправлять файлы.

Стиль общения:
- Четко и по делу, без лишних любезностей
- Краткие ответы по умолчанию, подробные - по запросу
- НЕ задавай уточняющие вопросы (исключения: отсутствие времени для напоминаний, фото без контекста)
- При незнании пользователем возможностей - кратко объясни функции
- Если пользователь ругается или долго пытается сделать одно и тоже и у него какие-то ошибки и т.д. предложи ему написать на личку - для этого надо ввести команду '/support'

Получаешь текущую дату/время автоматически при каждом запросе пользователя - не комментируй это ему и вообще не указывай информацию о дате и времени просто так."""

no_subscriber_message = (
    "🌸 Чтобы бот работал для тебя, сначала подпишись на канал "
    "<b><a href='https://t.me/sozdavai_media'>sozdav.ai</a></b>\n\n"
    "Почему это важно? Там мы делимся только отборными новостями, разбором трендов и инсайтами об ИИ, "
    "которых нет в ленте у большинства.\n"
    "Так ты получишь доступ не только к боту, но и к одному из лучших сообществ на тему ИИ и не только) ✨"
)


sozdavai_channel_id = "-1001972527440"

SUPPORTED_TEXT_FILE_TYPES = (
    # Самые популярные форматы (ежедневное использование)
    "txt", "csv", "json", "md", "html", "css", "js", "xml", "log", "sql",

    # Популярные языки программирования
    "py", "ts", "java", "cpp", "c", "php", "jsx", "tsx", "cs", "go",

    # Конфигурационные файлы (часто используемые)
    "yml", "yaml", "env", "ini", "cfg", "conf", "config", "toml",

    # Системные и скриптовые файлы
    "sh", "bash", "dockerfile", "makefile", "gitignore",

    # Специализированные форматы данных
    "tsv", "jsonl", "ndjson", "geojson",

    # Менее популярные языки программирования
    "rb", "rs", "swift", "kt", "scala", "h", "r", "matlab", "m",

    # Документация и разметка
    "rst", "tex", "latex", "adoc", "org",

    # XML-семейство (специфичные)
    "xsd", "xsl", "xslt", "soap", "wsdl", "rss", "atom",

    # Веб-технологии (старые/редкие)

    # Специализированные лог-файлы
    "access", "error", "debug", "trace"
)



sora_client = KieSora2Client()

async def on_startup(dispatcher):
    """Вызывается при запуске бота"""
    # Инициализируем сессию
    await sora_client._ensure_session()
    logger.info("Sora клиент инициализирован")

async def on_shutdown(dispatcher):
    """Вызывается при остановке бота"""
    # Закрываем сессию
    await sora_client.close()
    logger.info("Sora клиент остановлен")


async def send_initial(bot: Bot, chat_id: int) -> Message:
    text = (
        "⏳ *Генерация видео запущена*\n"
        "_Ожидайте, это может занять от 2 до 10 минут…_"
    )
    msg = await bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN)
    return msg

def _split_ids(s: str) -> list[str]:
    # "id1, id2, id3" -> ["id1","id2","id3"]
    return [x.strip() for x in (s or "").split(",") if x.strip()]

async def build_telegram_image_urls_from_ids(bot: Bot, ids: list[str]) -> list[str]:
    urls: list[str] = []
    for file_id in ids:
        try:
            f = await bot.get_file(file_id)  # -> aiogram.types.File
            if not f or not f.file_path:
                continue
            # Формируем публичный URL к файлу на серверах Telegram:
            url = f"https://api.telegram.org/file/bot{bot.token}/{f.file_path}"
            # Фильтр по расширению под требования KIE (jpeg/png/webp):
            if not f.file_path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                # при желании: логгировать, что формат отфильтрован
                continue
            urls.append(url)
        except Exception as e:
            # при желании: лог + continue
            continue
    return urls
