# app/models/promotion.py
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, String, Integer, DateTime, Boolean, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.package import Package
    from app.models.payment import Payment


class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # เก็บเป็นสตริง d/m/Y ตาม UI ได้ หรือถ้าจะเปลี่ยนเป็น DateTime ก็แก้ทั้งฟอร์ม/โค้ด
    start_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    end_date:   Mapped[str | None] = mapped_column(String(20), nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default=text("'active'")
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # --- Relationships ---
    packages: Mapped[list["Package"]] = relationship("Package", back_populates="promotion")
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="promotion")
