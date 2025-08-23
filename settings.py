import locale
import re
from os import getenv
import pytz

from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv, find_dotenv

from db.repository import subscriptions_repository
from utils.new_fitroom_api import FitroomClient


storage_bot = MemoryStorage()
storage_admin_bot = MemoryStorage()


load_dotenv(find_dotenv("../.env"))
main_bot_token = getenv("MAIN_BOT_TOKEN")
token_admin_bot = getenv("ADMIN_BOT_TOKEN")
test_bot_token = getenv("TEST_BOT_TOKEN")
business_connection_id = getenv("BUSINESS_CONNECTION_ID")


# settings.py
_current_bot = None

def set_current_bot(bot):
    global _current_bot
    _current_bot = bot

def get_current_bot():
    return _current_bot

MESSAGE_SPAM_TIMING=2

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
#
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

def get_current_datetime_string() -> str:
    # Берём текущее UTC-время и переводим в Москву
    now_msk = datetime.now(timezone.utc).astimezone(MSK)
    return now_msk.strftime("%Y-%m-%d %H:%M:%S")


def print_log(message: str) -> None:
    print(message)


class InputMessage(StatesGroup):
    enter_email = State()
    enter_user_context_state = State()
    enter_message_mailing = State()
    enter_admin_id = State()
    enter_promo_days = State()
    enter_max_activations_promo = State()


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

# Единственный экземпляр ассистента, который будет использоваться во всех хендлерах
# gpt_assistant = GPT()
# from utils.completions_gpt_tools import GPTCompletions
from utils.responses_gpt_tools import GPTResponses
gpt_assistant = GPTResponses()


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



sub_text = """🔓 Откройте весь потенциал нашего ИИ-бота — оформите подписку прямо здесь.

Базовый минимум для всех :
☑️ Бесплатные запросы к 3 LLM 
☑️ 5 фото через лучшие генеративные сервисы! 


Тарифы
• <b>Smart — 490 ₽/мес: </b>
✅ Безлимитный доступ к 6 LLM моделям, оптимально подбираемым под ваш запрос
✅ Работа с файлами и голосовыми сообщениями 
✅ Поиск в интернете
✅ Функция памяти и напоминаний 
✅ Генерация до 20 изображений 
в месяц 

• <b>Ultima — 990 ₽/мес: </b>
✅ Приоритетный канал доступа к 10 LLM!
✅ Безлимитная генерация изображений (GPT-images, Runway)
✅ Все опции тарифа «smart»

📅 Подписка активируется мгновенно, отменить можно в любой момент.

😊 Выберите подходящий уровень и нажмите «Оплатить» — мы уже готовы помочь!"""


buy_generations_text = """📸 У вас закончились доступные генерации.

<b>Доступные пакеты докупа:</b>
• <b>Докуп 1</b> — 390 ₽: 20 генераций
• <b>Докуп 2</b> — 890 ₽: 50 генераций

📅 Пакет активируется мгновенно и не продлевается автоматически. Отменять ничего не нужно — после расхода вы снова увидите предложение докупить.

😊 Выберите подходящий пакет и нажмите «Оплатить», чтобы продолжить генерировать контент!
"""


tools = [
    {
      "name": "generate_image",
      "description": "Запустить, если пользователь просит Сгенерировать одно или несколько ИЗОБРАЖЕНИЙ(НЕ ФАЙЛОВ) в случаях, если человек просит сделать изображение. Если пользователь просит сгенерировать несколько картинок 3 и меннее - то мы запускаем функцию один раз с параметром n равному количеству требуемых картинок. Если пользователь просит сгенерировать несколько разных изображений, то функция вызывается несколько раз по одному для каждого типа изображения с параметром n = 1. ЕСЛИ ПОЛЬЗОВАТЕЛЬ ПРОСИТ СГЕНЕРИРОВАТЬ БОЛЕЕ 4 ФОТОГРАФИИ И БОЛЕЕ ЗА РАЗ - отказываему ему и просим его указать число 3 или меньше. Если пользователь просит сгенерировать изображение.  Данный инструмент НЕЛЬЗЯ вызывать в случае, если пользователь хочет изменить какое-то изображение с наличием или добавлением хоть каких-либо людей",
      "strict": True,
      "parameters": {
        "type": "object",
        "properties": {
          "prompt": {
            "type": "string",
            "description": "Текстовый запрос для генерации изображения."
          },
          "n": {
            "type": "integer",
            "description": "Если пользователь просит сгенерировать несколько картинок 5 и меннее - то мы запускаем функцию один раз с параметром n равному количеству требуемых картинок. Если пользователь просит сгенерировать несколько разных изображений, то функция вызывается несколько раз по одному для каждого типа изображения с параметром n = 1",
            "minimum": 1,
            "maximum": 3
          },
          "size": {
            "type": "string",
            "description": "Размер выходного изображения.",
            "enum": [
              "1024x1024",
              "1024x1536",
              "1536x1024",
              "auto"
            ],
            "default": "1024x1024"
          },
          "quality": {
            "type": "string",
            "description": "Качество рендеринга.",
            "enum": [
              "low",
              "medium"
            ],
            "default": "medium"
          },
          "output_format": {
            "type": "string",
            "description": "Формат файла, который вернёт API.",
            "enum": [
              "png",
              "jpeg"
            ],
            "default": "png"
          },
          "user": {
            "type": "string",
            "description": "Необязательный идентификатор пользователя."
          }
        },
        "required": [
          "prompt",
          "n",
          "size",
          "quality",
          "output_format",
          "user"
        ],
        "additionalProperties": False
      }
    },
    {
      "name": "edit_image_only_with_peoples",
      "description": "Позволяет отредактировать или объединить несколько ИЗОБРАЖЕНИЙ(НЕ ФАЙЛОВ) с людьми, передаваемых в данную функцию.ДАННЫЙ ИНСТРУМЕНТ ВЫЗЫВАЕТСЯ ВСЕГДА, КОГДА ПОЛЬЗОВАТЕЛЬ ПРОСИТ ОБЪЕДИНИТЬ 2 И БОЛЕЕ ФОТОГРАФИИ ВНЕ ЗАВИСИМОСТИ ОТ ТОГО, ЧТО НА НИХ. Данная функция должна вызываться только в случаях, если идет речь об изображениях, где есть хотя бы один человек ИЛИ КОГДА НАДО ОБЪЕДИНИТЬ НЕСКОЛЬКО ИЗОБРАЖЕНИЙ",
      "strict": True,
      "parameters": {
        "type": "object",
        "properties": {
          "prompt": {
            "type": "string",
            "description": "Текстовый запрос для генерации изображения."
          },
          "ratio": {
            "type": "string",
            "description": "Разрешение изображения в формате 'ширина:высота' (например, '1920:1080'). Допустимые значения: '1920:1080', '1024:1024', '1080:1920', '1360:768', '1080:1080', '1168:880', '1440:1080', '1080:1440', '1808:768', '2112:912'.",
            "enum": [
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
            ],
            "default": "1024x1024"
          }
        },
        "required": [
          "prompt",
          "ratio"
        ],
        "additionalProperties": False
      }
    },
    {
        "name": "fitting_clothes",
        "description": "Запустить, когда пользователь хочет примерить одежду с одного фото на человека со второго фото. Если пользователь не прислал две фотографии, всё равно вызывай функцию — она вернёт пользователю инструкцию, что нужно прислать РОВНО две фотографии одним сообщением.",
        "strict": False,
        # <-- было True; отключаем строгую проверку, чтобы модель могла вызывать тул даже без всех аргументов
        "parameters": {
            "type": "object",
            "properties": {
                "cloth_type": {
                    "type": "string",
                    "description": "Как примерять одежду: 'lower' — только низ (брюки/юбки), 'upper' - только верх(рубашки, кофты, футболки и тд), 'full' — весь образ(в том числе платья, пальто и тд).",
                    "enum": ["lower", "full", "upper"],
                    "default": "full"  # <-- дефолт
                },
                "swap_photos": {
                    "type": "boolean",
                    "description": "False — человек на первом фото; True — человек на втором фото.",
                    "default": False  # <-- дефолт, БЕЗ enum на boolean
                }
            },
            "required": [],  # <-- ничего не требуем жёстко
            "additionalProperties": False
        }
    },
    {
      "name": "add_notification",
      "description": "Функция, которая вызывается в случае, если пользователь просит поставить уведомление или напоминание на какую-то дату и время (например, на 24.08.2025) или через какой-то временной промежуток (например через 30 минут или на послезавтра). ТЫ ОБЯЗАН ВСЕГДА УТОЧНИТЬ ВРЕМЯ У ПОЛЬЗОВАТЕЛЯ И НЕ ВЫЗЫВАТЬ ФУНКЦИЮ, ЕСЛИ ПОЛЬЗОАТЕЛЬ НЕ УКАЗАЛ КОНКРЕТНОЕ ВРЕМЯ. Если пользователь просит поставить уведомление БЕЗ ВРЕМЕНИ — функция не вызывается, и у пользователя спрашивается, на какое конкретно время нужно поставить напоминание в эту дату. Если пользователь указывает, что нужно установить напоминание на какое-то время, дату или через какой-то промежуток без указания, о чем напомнить — функция не вызывается, и задаем уточняющий вопрос о том, что нам нужно напомнить пользователю. ОБЯЗАТЕЛЬНО нужно отталкиваться от того, что сегодняшнюю дату и время пользователь пишет в своем промте.",
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
]


system_prompt = """Ты универсальный ассистент в тг боте, который помогает пользователю с любыми задачами и отвечает на вопросы. Ты обладаешь следующими возможностями:

1. Генерация изображений через модель gpt-image-1, если пользователь запросит.
2. Редактирование изображений с помощью runway, если требуется изменить существующее изображение (ДАННЫЙ ИНСТРУМЕНТ ВЫЗЫВАЕТСЯ ВСЕГДА, КОГДА ПОЛЬЗОВАТЕЛЬ ПРОСИТ ОБЪЕДИНИТЬ 2 И БОЛЕЕ ФОТОГРАФИИ ВНЕ ЗАВИСИМОСТИ ОТ ТОГО, ЧТО НА НИХ).
3. Поиск информации в интернете через инструмент search_web, если нужна актуальная информация.
4. Обработка голосовых сообщений и ответ в виде изображений или файлов.
5. Прием и обработка фото и файлов, а также помощь с ними.
6. Примерка одежды по фото(Данная функция запускается ТОЛЬКО ОДИН РАЗ ЗА ЗАПРОС ПОЛЬЗОВАТЕЛЯ! Запустить, если пользователь прислал ОБЯЗАТЕЛЬНО ДВЕ ФОТОГРАФИИ для того, чтобы примерить одежду со одного фото на человека со второго фото. Если пользователь хочет примерить одежду и при этом скинул только одно фото, то нужно заставить пользователя отправить оба фото ОДНИМ сообщением)
7. Генерация файлов различных форматов по запросу пользователя.
8. Создание напоминаний с помощью add_notification при указании конкретной даты и времени.(ТЫ ОБЯЗАН ВСЕГДА УТОЧНИТЬ ВРЕМЯ У ПОЛЬЗОВАТЕЛЯ И НЕ ВЫЗЫВАТЬ ФУНКЦИЮ, ЕСЛИ ПОЛЬЗОАТЕЛЬ НЕ УКАЗАЛ КОНКРЕТНОЕ ВРЕМЯ. если пользователь указал, когда отправить уведомления, но без конкретного времени - данная функция не вызывается и у пользователя уточняется время)

Если пользователь не знает, как обратиться, кратко объясни свои возможности. Отвечай кратко, но если нужно подробное объяснение, предоставь его.
"""