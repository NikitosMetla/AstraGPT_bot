from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, relationship

from db.base import BaseModel, CleanModel
from .users import Users


class VideoGenerationsPackets(BaseModel, CleanModel):
    """
    Таблица юзеров
    """
    __tablename__ = 'video_generations_packets'

    generations = Column(BigInteger, nullable=False, unique=False)
    price = Column(BigInteger, nullable=False)

    @property
    def stats(self) -> str:
        """
        :return:
        """
        return ""
