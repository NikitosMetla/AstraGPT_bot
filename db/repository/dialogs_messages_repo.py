from typing import Sequence, Any

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import DatabaseEngine
from db.models import DialogsMessages


class DialogsMessagesRepository:
    def __init__(self):
        self.session_maker = DatabaseEngine().create_session()

    async def add_message(self, user_id: int, message: Any):
        """
        Добавление сообщения в базу данных.
        """
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                try:
                    # Создаём объект сообщения и добавляем его в сессию
                    dialog_message = DialogsMessages(user_id=user_id, message=message)
                    session.add(dialog_message)
                except Exception as e:
                    # Логирование ошибки при добавлении
                    print(f"Error adding message: {e}")
                    return False
                return True

    async def get_messages_by_user_id(self, user_id: int) -> Sequence[DialogsMessages]:
        """
        Получение всех сообщений для пользователя по его ID.
        """
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(DialogsMessages).where(DialogsMessages.user_id == user_id)
                query = await session.execute(sql)
                return query.scalars().all()

    async def get_message_by_message_id(self, message_id: int) -> DialogsMessages:
        """
        Получение конкретного сообщения по ID сообщения.
        """
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(DialogsMessages).where(DialogsMessages.id == message_id)
                query = await session.execute(sql)
                return query.scalars().one_or_none()

    async def select_all_messages(self) -> Sequence[DialogsMessages]:
        """
        Получение всех сообщений из таблицы.
        """
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(DialogsMessages)
                query = await session.execute(sql)
                return query.scalars().all()

    async def delete_message_by_message_id(self, message_id: int):
        """
        Удаление сообщения по ID сообщения.
        """
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = delete(DialogsMessages).where(DialogsMessages.id == message_id)
                await session.execute(sql)
                await session.commit()
                return True
