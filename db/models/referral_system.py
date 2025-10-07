from sqlalchemy import Column, BigInteger, ForeignKey, String, Boolean
from sqlalchemy.orm import relationship, Mapped

from db.base import BaseModel, CleanModel
from .users import Users


class ReferralSystem(BaseModel, CleanModel):
    """Таблица запросов к gpt"""
    __tablename__ = 'referral_system'

    promo_code = Column(String, nullable=False, primary_key=True, unique=True)
    activations = Column(BigInteger, nullable=True, default=0, unique=False)
    days_sub = Column(BigInteger, nullable=False, default=7, unique=False)
    max_activations = Column(BigInteger, nullable=True, unique=False)
    type_promo = Column(String, nullable=False, unique=False, default="standard")
    active = Column(Boolean, nullable=False, default=True, unique=False)
    max_generations = Column(BigInteger, nullable=False)
    max_video_generations = Column(BigInteger, nullable=False, default=0)
    with_voice = Column(Boolean, nullable=False, default=False)
    with_files = Column(Boolean, nullable=False, default=False)
    web_search = Column(Boolean, nullable=False, default=False)

    @property
    def stats(self) -> str:
        """
       :return:
        """
        return ""

    def __str__(self) -> str:
        return f"<{self.__tablename__}:{self.id}>"

    def __repr__(self):
        return self.__str__()
