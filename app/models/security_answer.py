# app/models/security_answer.py
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import BigInteger, String, Text, DateTime, ForeignKey, func
from app.db import Base

class SecurityAnswer(Base):
    __tablename__ = "security_answers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # ใช้ข้อความคำถาม (ตรงกับ schema ปัจจุบัน)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user = relationship("User", back_populates="security_answers")
