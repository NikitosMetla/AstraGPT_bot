import locale
import re
from os import getenv
import pytz

from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv, find_dotenv

from db.repository import subscriptions_repository

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

from datetime import datetime

def get_current_datetime_string() -> str:
    """
    Возвращает текущую дату и время в московском часовом поясе в формате строки 'YYYY-MM-DD HH:MM:SS'.
    """
    moscow_tz = pytz.timezone('Europe/Moscow')
    utc_now = datetime.now()
    moscow_now = utc_now.replace(tzinfo=pytz.UTC).astimezone(moscow_tz) if utc_now.tzinfo is None else utc_now.astimezone(moscow_tz)
    return moscow_now.strftime("%Y-%m-%d %H:%M:%S")

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
gpt_assistant = GPT()

from utils.completions_gpt_tools import GPTCompletions

gpt_completions = GPTCompletions()


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
                        "type": "function",
                        "function": {
                            "name": "generate_image",
                            "description": "Генерирует изображение по текстовому описанию",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "prompt": {
                                        "type": "string",
                                        "description": "Описание изображения для генерации"
                                    },
                                    "n": {
                                        "type": "integer",
                                        "description": "Количество изображений",
                                        "default": 1
                                    },
                                    "size": {
                                        "type": "string",
                                        "description": "Размер изображения",
                                        "default": "1024x1024"
                                    },
                                    "quality": {
                                        "type": "string",
                                        "description": "Качество изображения",
                                        "default": "low"
                                    },
                                    "edit_existing_photo": {
                                        "type": "boolean",
                                        "description": "Редактировать существующее фото",
                                        "default": False
                                    }
                                },
                                "required": ["prompt"]
                            }
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "edit_image_only_with_peoples",
                            "description": "Редактирует изображения с людьми используя Runway API",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "prompt": {
                                        "type": "string",
                                        "description": "Описание изменений изображения"
                                    },
                                    "ratio": {
                                        "type": "string",
                                        "description": "Соотношение сторон",
                                        "default": "1920:1080"
                                    }
                                },
                                "required": ["prompt"]
                            }
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "search_web",
                            "description": "Поиск информации в интернете",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "query": {
                                        "type": "string",
                                        "description": "Поисковый запрос"
                                    }
                                },
                                "required": ["query"]
                            }
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "add_notification",
                            "description": "Добавляет уведомление на определенное время",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "when_send_str": {
                                        "type": "string",
                                        "description": "Дата и время отправки в формате YYYY-MM-DD HH:MM:SS"
                                    },
                                    "text_notification": {
                                        "type": "string",
                                        "description": "Текст уведомления"
                                    }
                                },
                                "required": ["when_send_str", "text_notification"]
                            }
                        }
                    }
                ]