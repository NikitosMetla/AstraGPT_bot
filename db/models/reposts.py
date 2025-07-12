from datetime import time
from sqlalchemy import Column, BigInteger, String, Boolean, Integer, ForeignKey, Time

from db.base import BaseModel, CleanModel


class Reposts(BaseModel, CleanModel):
    """
    Таблица юзеров
    """
    __tablename__ = 'reposts'

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
