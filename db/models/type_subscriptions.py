from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, relationship

from db.base import BaseModel, CleanModel
from .users import Users


class TypeSubscriptions(BaseModel, CleanModel):
    """
    Таблица юзеров
    """
    __tablename__ = 'type_subscriptions'

    plan_name = Column(String, nullable=False , unique=True)
    price = Column(BigInteger, nullable=False)
    max_generations = Column(BigInteger, nullable=False)
    max_video_generations = Column(BigInteger, nullable=False)
    with_voice = Column(Boolean, nullable=False, default=False)
    with_files = Column(Boolean, nullable=False, default=False)
    web_search = Column(Boolean, nullable=False, default=False)
    from_promo = Column(Boolean, nullable=False, default=False)

    @property
    def stats(self) -> str:
        """
        :return:
        """
        return ""

    def __str__(self) -> str:
        return f"<{self.__tablename__}:{self.user_id}>"

    def __repr__(self):
        return self.__str__()
