from typing import Sequence

from sqlalchemy import select, or_, update, delete, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import DatabaseEngine
from db.models import GenerationsPackets


class GenerationsPacketsRepository:
    def __init__(self):
        self.session_maker = DatabaseEngine().create_session()

    async def add_generations_packet(self,
                               generations: int, price: int) -> bool:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                user = GenerationsPackets(generations=generations, price=price)
                try:
                    session.add(user)
                except Exception:
                    return False
                return True

    async def get_generations_packet_by_id(self, packet_id: int) -> GenerationsPackets:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(GenerationsPackets).where(or_(GenerationsPackets.id == packet_id))
                query = await session.execute(sql)
                return query.scalars().one_or_none()

    async def select_all_generations_packets(self) -> Sequence[GenerationsPackets]:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(GenerationsPackets)
                query = await session.execute(sql)
                return query.scalars().all()

    async def delete_generations_packet_by_id(self, packet_id: int):
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = delete(GenerationsPackets).where(or_(GenerationsPackets.id == packet_id))
                await session.execute(sql)
                await session.commit()




