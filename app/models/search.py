# app/models/search.py
from __future__ import annotations
from datetime import datetime
from typing import Optional, Dict, List
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, ForeignKey, DateTime, JSON, func

from app.db import Base

class SearchSession(Base):
    __tablename__ = "search_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    params_json: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="done")

    user = relationship("User")
    results: Mapped[List["SearchSessionCar"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

class SearchSessionCar(Base):
    __tablename__ = "search_session_cars"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("search_sessions.id", ondelete="CASCADE"), index=True)
    # ถ้า __tablename__ ของโมเดลรถคุณไม่ใช่ "car_cache" ให้แก้ ForeignKey ให้ตรง
    car_id: Mapped[int] = mapped_column(ForeignKey("car_cache.id"), index=True)
    rank: Mapped[int] = mapped_column(Integer)

    session = relationship("SearchSession", back_populates="results")
    car = relationship("CarCache")
