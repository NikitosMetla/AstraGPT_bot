from typing import Sequence, Optional

from sqlalchemy import select, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import DatabaseEngine
from db.models import ReferralSystem


class ReferralSystemRepository:
    def __init__(self):
        self.session_maker = DatabaseEngine().create_session()

        self.session_maker = DatabaseEngine().create_session()

    async def add_promo(self,
                        promo_code: str,
                        days_sub: int = 30,
                        max_activations: int | None = None,
                        max_generations: int = 0,
                        with_voice: bool = False,
                        with_files: bool = False,
                        web_search: bool = False,
                        active: bool = True) -> bool:
        """

        Создание нового промокода
        """
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = ReferralSystem(
                    promo_code=promo_code,
                    days_sub=days_sub,
                    max_activations=max_activations,
                    max_generations=max_generations,
                    with_voice=with_voice,
                    with_files=with_files,
                    web_search=web_search,
                    active=active,
                )
                try:
                    session.add(sql)
                except Exception:
                    return False
                return True

    async def select_all_promo(self) -> Sequence[ReferralSystem]:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(ReferralSystem)
                query = await session.execute(sql)
                return query.scalars().all()

    async def select_all_promo_codes(self) -> set:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(ReferralSystem.promo_code)
                query = await session.execute(sql)
                return set(query.scalars().all())

    async def get_promo_by_promo_code(self, promo_code: str) -> ReferralSystem:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(ReferralSystem).where(or_(ReferralSystem.promo_code == promo_code))
                query = await session.execute(sql)
                return query.scalars().one_or_none()

    async def update_activations_by_promo_id(self, promo_id: int):
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = update(ReferralSystem).values({
                    ReferralSystem.activations: ReferralSystem.activations + 1,
                }).where(or_(ReferralSystem.id == promo_id))
                await session.execute(sql)
                await session.commit()


