from datetime import datetime
from typing import Sequence, Optional

from sqlalchemy import select, or_, update, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import DatabaseEngine
from db.models import Notifications


class NotificationsRepository:
    def __init__(self):
        self.session_maker = DatabaseEngine().create_session()

    async def add_notification(self,
                            when_send: datetime,
                            user_id: int,
                            text_notification: str
                            ) -> bool:
        """    when_send = Column(DateTime, unique=False, nullable=False)
    text_notification = Column(String, unique=False, nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.user_id'), nullable=False)
    user: Mapped[Users] = relationship("Users", backref=__tablename__, cascade='all', lazy='subquery')"""
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = Notifications(user_id=user_id, when_send=when_send, text_notification=text_notification)
                try:
                    session.add(sql)
                except Exception:
                    return False
                return True

    async def get_notification_info_by_id(self, id: int) -> Optional[Notifications]:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(Notifications).where(or_(Notifications.id == id))
                query = await session.execute(sql)
                return query.scalars().one_or_none()

    async def select_all_notifications(self) -> Sequence[Notifications]:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(Notifications)
                query = await session.execute(sql)
                return query.scalars().all()

    async def select_all_active_notifications(self) -> Sequence[Notifications]:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(Notifications).where(or_(Notifications.active == True))
                query = await session.execute(sql)
                return query.scalars().all()

    async def get_notifications_by_user_id(self, user_id: int) -> Sequence[Notifications]:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(Notifications).where(or_(Notifications.user_id == user_id))
                query = await session.execute(sql)
                return query.scalars().all()

    async def get_active_notifications_by_user_id(self, user_id: int) -> Sequence[Notifications]:
        """Получает все активные уведомления конкретного пользователя"""
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(Notifications).where(
                    and_(Notifications.user_id == user_id, Notifications.active == True)
                ).order_by(Notifications.id)
                query = await session.execute(sql)
                return query.scalars().all()

    async def update_active_by_notification_id(self, notification_id: int):
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = update(Notifications).values({
                    Notifications.active: False
                }).where(or_(Notifications.id == notification_id))
                await session.execute(sql)
                await session.commit()

    async def delete_active_by_notification_id(self, notification_id: int):
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = delete(Notifications).where(or_(Notifications.id == notification_id))
                await session.execute(sql)
                await session.commit()



