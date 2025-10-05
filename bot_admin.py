from aiogram import Dispatcher, Bot, types

import asyncio

from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from db.engine import DatabaseEngine
from handlers.admin_bot_handlers import admin_router
# from handlers.admin_bot_handlers import admin_router
from settings import token_admin_bot, storage_admin_bot, initialize_logger, set_current_loop

admin_bot = Bot(token=token_admin_bot, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


async def main():
    db_engine = DatabaseEngine()
    set_current_loop(asyncio.get_running_loop())
    initialize_logger()
    await db_engine.proceed_schemas()
    print(await admin_bot.get_me())
    await admin_bot.delete_webhook(drop_pending_updates=True)
    dp = Dispatcher(storage=storage_admin_bot)
    dp.include_routers(admin_router)
    await dp.start_polling(admin_bot)


if __name__ == "__main__":
    asyncio.run(main())
