import os
import asyncio
from agents import set_default_openai_key, Agent, WebSearchTool, Runner
from dotenv import find_dotenv, load_dotenv

from utils.parse_gpt_text import sanitize_with_links

# 1. Настройка API-ключа
load_dotenv(find_dotenv())
API_KEY: str | None = os.getenv("GPT_TOKEN") or os.getenv("OPENAI_API_KEY")
if not API_KEY:
    raise ValueError("Переменная окружения OPENAI_API_KEY не задана")
set_default_openai_key(API_KEY)

# 2. Создание агента с инструментом веб-поиска
agent = Agent(
    name="WebSearchAgent",
    tools=[WebSearchTool()],
    model="gpt-5-mini",

)

async def search_prompt(prompt: str) -> str:
    result = await Runner.run(agent, prompt)
    return result.final_output