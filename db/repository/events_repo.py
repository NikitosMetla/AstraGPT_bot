from datetime import datetime, timedelta
from typing import Sequence, Optional

from dateutil.relativedelta import relativedelta
from sqlalchemy import select, or_, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import DatabaseEngine
from db.models import Events


class EventsRepository:
    def __init__(self):
        self.session_maker = DatabaseEngine().create_session()

    async def add_event(self,
                            user_id: int,
                            event_type: str) -> bool:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = Events(user_id=user_id, event_type=event_type)
                try:
                    session.add(sql)
                except Exception:
                    return False
                return True

    async def get_event_by_id(self, id: int) -> Optional[Events]:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(Events).where(or_(Events.id == id))
                query = await session.execute(sql)
                return query.scalars().one_or_none()

    async def select_all_events(self) -> Sequence[Events]:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(Events)
                query = await session.execute(sql)
                return query.scalars().all()

    async def get_events_by_user_id(self, user_id: int) -> Sequence[Events]:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(Events).where(or_(Events.user_id == user_id))
                query = await session.execute(sql)
                return query.scalars().all()

    async def get_last_event_by_user_id(self, user_id: int) -> Optional[Events]:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(Events).where(or_(Events.user_id == user_id)).order_by(Events.creation_date.desc())
                query = await session.execute(sql)
                return query.scalars().first()

    async def update_event(self, event: Events) -> bool:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                try:
                    await session.merge(event)
                except Exception:
                    return False
        return True

    async def get_users_event_stats(self) -> dict[str, int]:
        """
        Возвращает словарь с количеством уникальных пользователей,
        создавших события за указанные периоды:
         - 'hour'    — за последний час
         - 'day'     — за последние 24 часа
         - 'week'    — за последние 7 дней
         - 'month'   — за последний календарный месяц (30–31 день)
         - 'quarter' — за последние 3 месяца
        """
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                now = datetime.utcnow()

                periods = {
                    'hour':    now - timedelta(hours=1),
                    'day':     now - timedelta(days=1),
                    'week':    now - timedelta(weeks=1),
                    'month':   now - relativedelta(months=1),
                    'quarter': now - relativedelta(months=3),
                }

                stats: dict[str, int] = {}
                for label, threshold in periods.items():
                    stmt = (
                        select(func.count(func.distinct(Events.user_id)))
                        .where(Events.creation_date >= threshold)
                    )
                    result = await session.execute(stmt)
                    # .scalar() выдаёт None, если в БД нет строк — заменяем на 0
                    stats[label] = result.scalar() or 0

                return stats

