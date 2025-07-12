from aiogram import Dispatcher, Bot, types

import asyncio

from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from db.engine import DatabaseEngine
from handlers.admin_bot_handlers import admin_router
# from handlers.admin_bot_handlers import admin_router
from settings import token_admin_bot, storage_admin_bot

admin_bot = Bot(token=token_admin_bot, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


async def main():
    db_engine = DatabaseEngine()
    await db_engine.proceed_schemas()
    print(await admin_bot.get_me())
    await admin_bot.delete_webhook(drop_pending_updates=True)
    dp = Dispatcher(storage=storage_admin_bot)
    dp.include_routers(admin_router)
    await dp.start_polling(admin_bot)


if __name__ == "__main__":
    asyncio.run(main())
