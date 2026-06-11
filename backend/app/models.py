from sqlalchemy import Column, Integer, String, Text, Date, DateTime
from sqlalchemy.sql import func
from .database import Base

class NurseryInfo(Base):
    __tablename__ = "nursery_info"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    info_type = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    date = Column(Date, nullable=True)
    event_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    items = Column(Text, nullable=True)
    status = Column(String(20), default="未対応")
    priority = Column(String(10), default="普通")
    tags = Column(Text, nullable=True)
    memo = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
