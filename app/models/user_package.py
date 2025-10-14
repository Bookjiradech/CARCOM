from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, Integer, String, DateTime, ForeignKey, func
from app.db import Base

class UserPackage(Base):
    __tablename__ = "user_packages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id", ondelete="RESTRICT"), index=True, nullable=False)

    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remaining_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    source_payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
