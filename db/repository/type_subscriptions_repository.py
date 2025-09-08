from typing import Sequence

from sqlalchemy import select, or_, update, delete, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import DatabaseEngine
from db.models import TypeSubscriptions


class TypeSubscriptionsRepository:
    def __init__(self):
        self.session_maker = DatabaseEngine().create_session()

    async def add_type_subscription(self,
                               with_voice: bool | None = False, max_generations: int | None = None,
                               with_files: bool | None = None, plan_name: str | None = None, price: int | None = None,
                                web_search: bool | None = False) -> bool:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                user = TypeSubscriptions(with_voice=with_voice, plan_name=plan_name,
                                     with_files=with_files, max_generations=max_generations,
                                         price=price, web_search=web_search)
                try:
                    session.add(user)
                except Exception:
                    return False
                return True

    async def get_type_subscription_by_id(self, type_id: int) -> TypeSubscriptions:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(TypeSubscriptions).where(or_(TypeSubscriptions.id == type_id))
                query = await session.execute(sql)
                return query.scalars().one_or_none()

    async def get_type_subscription_by_plan_name(self, plan_name: str) -> TypeSubscriptions:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(TypeSubscriptions).where(or_(TypeSubscriptions.plan_name == plan_name))
                query = await session.execute(sql)
                return query.scalars().one_or_none()

    async def select_all_type_subscriptions(self) -> Sequence[TypeSubscriptions]:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(TypeSubscriptions)
                query = await session.execute(sql)
                return query.scalars().all()

    async def delete_type_subscription_by_id(self, type_id: int):
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = delete(TypeSubscriptions).where(or_(TypeSubscriptions.id == type_id))
                await session.execute(sql)
                await session.commit()




