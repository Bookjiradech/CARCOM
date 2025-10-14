# app/models/user.py
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING

from flask_login import UserMixin
from sqlalchemy import BigInteger, String, DateTime, Boolean, text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.payment import Payment
    from app.models.security_answer import SecurityAnswer


class User(UserMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default=text("'active'"),
    )
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=func.now(), onupdate=func.now()
    )

    # --- Relationships ---
    payments: Mapped[list["Payment"]] = relationship(
        "Payment", back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    security_answers = relationship(
    "SecurityAnswer",
    back_populates="user",
    cascade="all, delete-orphan",
    passive_deletes=True,
    )

    def get_id(self) -> str:
        return str(self.id)
