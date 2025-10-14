# app/models/payment.py
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger, String, Integer, Numeric, DateTime, ForeignKey, func, text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.package import Package
    from app.models.promotion import Promotion


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    package_id: Mapped[int] = mapped_column(
        ForeignKey("packages.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    promotion_id: Mapped[int | None] = mapped_column(
        ForeignKey("promotions.id", ondelete="SET NULL"), nullable=True
    )

    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    vat: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)

    method: Mapped[str] = mapped_column(String(20), nullable=False, default="qr")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'")
    )
    slip_url: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # --- Relationships (ใช้ back_populates ทั้งสองฝั่ง) ---
    user: Mapped["User"] = relationship("User", back_populates="payments")
    package: Mapped["Package"] = relationship("Package", back_populates="payments")
    promotion: Mapped["Promotion | None"] = relationship("Promotion", back_populates="payments")
