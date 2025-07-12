import asyncio
import datetime


from aiogram import Dispatcher, Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

from db.engine import DatabaseEngine
from handlers.user_handler import standard_router

from settings import storage_bot, token_design_level, test_bot_token

main_bot = Bot(token=test_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))



async def main():
    # from utils.message_throttling import MessageSpamMiddleware
    from utils.message_throttling import CombinedMiddleware
    logger.add(f"logs/{datetime.date.today()}.log", format="{time:DD-MMM-YYYY HH:mm:ss} | {level:^25} | {message}",
               enqueue=True, rotation="00:00")
    logger.level("JOIN", no=60, color="<green>")
    logger.level("SPAM", no=60, color="<yellow>")
    logger.level("ERROR_HANDLER", no=60, color="<red>")
    db_engine = DatabaseEngine()
    await db_engine.proceed_schemas()
    print(await main_bot.get_me())
    await main_bot.delete_webhook(drop_pending_updates=True)
    dp = Dispatcher(storage=storage_bot)
    dp.message.middleware.register(CombinedMiddleware())
    dp.include_routers(standard_router)
    await dp.start_polling(main_bot, polling_timeout=3, skip_updates=False)


if __name__ == "__main__":
    asyncio.run(main())

