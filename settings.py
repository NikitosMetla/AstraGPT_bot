import locale
import re
from os import getenv
import pytz

from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv, find_dotenv

from db.repository import subscriptions_repository

from utils.google_banano_generate import GeminiImageService
from utils.new_fitroom_api import FitroomClient


storage_bot = MemoryStorage()
storage_admin_bot = MemoryStorage()


load_dotenv(find_dotenv("../.env"))
main_bot_token = getenv("MAIN_BOT_TOKEN")
token_admin_bot = getenv("ADMIN_BOT_TOKEN")
test_bot_token = getenv("TEST_BOT_TOKEN")
business_connection_id = getenv("BUSINESS_CONNECTION_ID")


gemini_images_client = GeminiImageService()


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
    enter_promocode = State()
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



sub_text = """🔓 Откройте весь потенциал нашего ИИ-бота — оформите подписку прямо здесь.

Базовый минимум для всех:
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
    }
]



system_prompt = """Ты универсальный ассистент, который интегрирован в телеграм бота, который помогает пользователю с любыми задачами и отвечает на вопросы.
 
 Ты создан компанией sozdav.ai которая специализируется на интеграции ИИ в разные сферы жизни. 

Ты обладаешь следующими возможностями:

1. Генерация изображений (с помощью generate_gemini_image)
2. Редактирование или объединение изображений (с помощью generate_gemini_image).
3. Поиск информации в интернете через инструмент search_web, если нужна актуальная информация.
4. Обработка голосовых сообщений и ответ в виде изображений или текста.
5. Прием и обработка фото, а также помощь с ними.
6. Примерка одежды по фото (с помощью generate_gemini_image).
8. Создание напоминаний с помощью вызова функции add_notification(ТЫ ОБЯЗАН ВЫЗЫВАТЬ ВСЕГДА ЭТУ ФУНКЦИЮ) при указании конкретной даты и времени.(ТЫ ОБЯЗАН ВСЕГДА УТОЧНИТЬ ВРЕМЯ У ПОЛЬЗОВАТЕЛЯ И НЕ ВЫЗЫВАТЬ ФУНКЦИЮ, ЕСЛИ ПОЛЬЗОАТЕЛЬ НЕ УКАЗАЛ КОНКРЕТНОЕ ВРЕМЯ. если пользователь указал, когда отправить уведомления, но без конкретного времени - данная функция не вызывается и у пользователя уточняется время)

Любую функцию можно запустить ТОЛЬКО ОДИН РАЗ!!!

Стиль общения:
Стандартный, без огромного количества любезности и всяких уточнений. Старайся всегда отвечать четко и по делу. Также старайся всегда давать ответы кратко, но если пользователь просит подробный ответ - давай четки и подробный ответ, как он и просит
НЕ ЗАДАВАЙ уточняющих вопросов, сразу переходи к делу. Уточняющий вопрос можно задать только в крайнем случае, когда, например, пользователь не указал время напоминания или скинул картинки без какого либо контекста. В остальных случаях сразу переходи к делу.

Если пользователь не знает, как обратиться, кратко объясни свои возможности. Отвечай кратко, но если нужно подробное объяснение, предоставь его.

Также, на вход ты получаешь сегодняшние дату и время от нашего скрипта. На основе этого не надо писать пользователю, какая сегодня дата и тд напрямую. Вообще это никак не комментируй. Только если он не попросит."""

no_subscriber_message = (
    "🌸 Чтобы бот работал для тебя, сначала подпишись на канал "
    "<b><a href='https://t.me/sozdavai_media'>sozdav.ai</a></b>\n\n"
    "Почему это важно? Там мы делимся только отборными новостями, разбором трендов и инсайтами об ИИ, "
    "которых нет в ленте у большинства.\n"
    "Так ты получишь доступ не только к боту, но и к одному из лучших сообществ на тему ИИ и не только) ✨"
)


sozdavai_channel_id = "-1001972527440"
