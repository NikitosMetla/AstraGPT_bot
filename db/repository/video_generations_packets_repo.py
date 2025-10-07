from typing import Sequence

from sqlalchemy import select, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import DatabaseEngine
from db.models import VideoGenerationsPackets


class VideoVideoGenerationsPacketsRepository:
    def __init__(self):
        self.session_maker = DatabaseEngine().create_session()

    async def add_video_generations_packet(self,
                               generations: int, price: int) -> bool:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                user = VideoGenerationsPackets(generations=generations, price=price)
                try:
                    session.add(user)
                except Exception:
                    return False
                return True

    async def get_video_generations_packet_by_id(self, packet_id: int) -> VideoGenerationsPackets:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(VideoGenerationsPackets).where(or_(VideoGenerationsPackets.id == packet_id))
                query = await session.execute(sql)
                return query.scalars().one_or_none()

    async def select_all_video_generations_packets(self) -> Sequence[VideoGenerationsPackets]:
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = select(VideoGenerationsPackets)
                query = await session.execute(sql)
                return query.scalars().all()

    async def delete_video_generations_packet_by_id(self, packet_id: int):
        async with self.session_maker() as session:
            session: AsyncSession
            async with session.begin():
                sql = delete(VideoGenerationsPackets).where(or_(VideoGenerationsPackets.id == packet_id))
                await session.execute(sql)
                await session.commit()




