from sqlalchemy import Column, BigInteger, ForeignKey, Boolean, String, DateTime
from sqlalchemy.orm import relationship, Mapped

from db.base import BaseModel, CleanModel
from .users import Users


class Notifications(BaseModel, CleanModel):
    """Таблица операций по оплате"""
    __tablename__ = 'notifications'

    when_send = Column(DateTime, unique=False, nullable=False)
    active = Column(Boolean, unique=False, nullable=False, default=True)
    text_notification = Column(String, unique=False, nullable=False)
    user_id = Column(BigInteger, ForeignKey('users.user_id'), nullable=False)
    user: Mapped[Users] = relationship("Users", backref=__tablename__, cascade='all', lazy='subquery')

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
