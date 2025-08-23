from sqlalchemy import Column, ForeignKey, BigInteger
from sqlalchemy.dialects.postgresql import JSONB

from db.base import BaseModel, CleanModel


class DialogsMessages(BaseModel, CleanModel):
    __tablename__ = 'dialogs_messages'
    user_id = Column(BigInteger, ForeignKey('users.user_id'), nullable=False)
    message = Column(JSONB, nullable=False)