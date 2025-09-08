from datetime import time
from sqlalchemy import Column, BigInteger, String, Boolean, Integer, ForeignKey, Time

from db.base import BaseModel, CleanModel


class Users(BaseModel, CleanModel):
    """
    Таблица юзеров
    """
    __tablename__ = 'users'

    user_id = Column(BigInteger, primary_key=True, unique=True, nullable=False)
    username = Column(String, nullable=True, unique=False)
    standard_ai_threat_id = Column(String, nullable=True, unique=True)
    gender = Column(String, nullable=True, unique=False)
    age = Column(String, nullable=True, unique=False)
    name = Column(String, nullable=True, unique=False)
    active_subscription = Column(Boolean, nullable=False, unique=False, default=False)
    confirm_politic = Column(Boolean, nullable=False, unique=False, default=False)
    # full_registration = Column(Boolean, nullable=False, unique=False, default=False)
    activate_promo = Column(Boolean, nullable=False, unique=False, default=False)
    email = Column(String, nullable=True, unique=False)
    context = Column(String, nullable=True, unique=False)
    model_type = Column(String, nullable=True, unique=False, default="gpt-4o-mini")
    last_image_id = Column(String, nullable=True, unique=False)
    last_response_id = Column(String, nullable=True, unique=False)
    type_model = Column(String, nullable=False, unique=False, default="universal")

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
