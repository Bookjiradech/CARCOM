# app/models/package.py
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger, String, Integer, Boolean, DateTime, Numeric, ForeignKey, func, text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.payment import Payment
    from app.models.promotion import Promotion


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    price_thb: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_lifetime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default=text("'active'")
    )

    promotion_id: Mapped[int | None] = mapped_column(
        ForeignKey("promotions.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # --- Relationships ---
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="package")
    promotion: Mapped["Promotion | None"] = relationship("Promotion", back_populates="packages")
