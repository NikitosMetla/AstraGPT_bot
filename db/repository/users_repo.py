from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import select, or_, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import DatabaseEngine
from db.models import Users


class UserRepository:
    def __init__(self):
        self.session_maker = DatabaseEngine().create_session()

    async def add_user(self, user_id: int, username: str):
        """user_id = Column(BigInteger, primary_key=True, unique=True, nullable=False)
            username = Column(String, nullable=True, unique=False)
            donate = Column(Boolean, default=False, unique=False)
            activate_trial_period = Column(Boolean, default=True, unique=False)
            end_trial_period = Column(Boolean, default=False, unique=False)
            notification = Column(Boolean, default=True, unique=False)
            notification_time = Column(Time, nullable=True, unique=False, default=time(23, 0))
            day_now_id = Column(BigInteger, ForeignKey("days.id"), nullable=True)"""
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                user = Users(user_id=user_id, username=username)
                try:
                    session.add(user)
                    # await session.commit()
                except Exception:
                    return False
                return True

    # async def update_language_id_by_user_id(self, user_id: int, language: int):
    #     async with self.session_maker() as session:
    #         session: AsyncSession
    #         async with session.begin():
    #             sql = update(Users).values({
    #                 Users.language: language
    #             }).where(or_(Users.user_id == user_id))
    #             await session.execute(sql)
    #             await session.commit()

    async def get_user_by_user_id(self, user_id: int) -> Users:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(Users).where(or_(Users.user_id == user_id))
                query = await session.execute(sql)
                return query.scalars().one_or_none()

    async def update_email_by_user_id(self, user_id: int, email: str):
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = update(Users).values({
                    Users.email: email
                }).where(or_(Users.user_id == user_id))
                await session.execute(sql)
                await session.commit()

    async def select_all_users(self) -> Sequence[Users]:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(Users)
                query = await session.execute(sql)
                return query.scalars().all()

    async def update_thread_id_by_user_id(self, user_id: int, thread_id: str):
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = update(Users).values({
                    Users.standard_ai_threat_id: thread_id
                }).where(or_(Users.user_id == user_id))
                await session.execute(sql)
                await session.commit()

    async def update_model_type_by_user_id(self, user_id: int, model_type: str):
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = update(Users).values({
                    Users.model_type: model_type
                }).where(or_(Users.user_id == user_id))
                await session.execute(sql)
                await session.commit()

    async def update_context_by_user_id(self, user_context: str, user_id: int):
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = update(Users).values({
                    Users.context: user_context
                }).where(or_(Users.user_id == user_id))
                await session.execute(sql)
                await session.commit()

    async def update_last_photo_id_by_user_id(self, photo_id: str, user_id: int):
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = update(Users).values({
                    Users.last_image_id: photo_id
                }).where(or_(Users.user_id == user_id))
                await session.execute(sql)
                await session.commit()

    async def update_last_response_id_by_user_id(self, last_response_id: str, user_id: int):
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = update(Users).values({
                    Users.last_response_id: last_response_id
                }).where(or_(Users.user_id == user_id))
                await session.execute(sql)
                await session.commit()

    async def get_user_creation_statistics(self) -> dict[str, int]:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                now = datetime.now()

                day_ago = now - timedelta(days=1)
                week_ago = now - timedelta(weeks=1)
                month_ago = now - timedelta(days=30)  # упрощённый вариант
                quarter_ago = now - timedelta(days=90)  # упрощённый вариант

                # За день
                day_count_sql = select(func.count(Users.user_id)).where(Users.creation_date >= day_ago)
                day_count_result = await session.execute(day_count_sql)
                day_count = day_count_result.scalar() or 0

                # За неделю
                week_count_sql = select(func.count(Users.user_id)).where(Users.creation_date >= week_ago)
                week_count_result = await session.execute(week_count_sql)
                week_count = week_count_result.scalar() or 0

                # За месяц
                month_count_sql = select(func.count(Users.user_id)).where(Users.creation_date >= month_ago)
                month_count_result = await session.execute(month_count_sql)
                month_count = month_count_result.scalar() or 0

                # За квартал
                quarter_count_sql = select(func.count(Users.user_id)).where(Users.creation_date >= quarter_ago)
                quarter_count_result = await session.execute(quarter_count_sql)
                quarter_count = quarter_count_result.scalar() or 0

                all_time_sql = select(func.count(Users.user_id))
                all_time_result = await session.execute(all_time_sql)
                all_time_count = all_time_result.scalar() or 0

                return {
                    'day': day_count,
                    'week': week_count,
                    'month': month_count,
                    'quarter': quarter_count,
                    "all_time": all_time_count,
                }

    # async def decrease_ai_attempts(self, user_id: int):
    #     async with self.session_maker() as session:
    #         session: AsyncSession
    #         async with session.begin():
    #             sql = update(Users).values({Users.ai_attempts: Users.ai_attempts - 1}).where(or_(Users.user_id == user_id))
    #             await session.execute(sql)
    #             await session.commit()
    #
    # async def update_ai_attempts(self, user_id: int):
    #     async with self.session_maker() as session:
    #         session: AsyncSession
    #         async with session.begin():
    #             sql = update(Users).values({Users.ai_attempts: 3}).where(or_(Users.user_id == user_id))
    #             await session.execute(sql)
    #             await session.commit()

