# backend/app/models.py
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Boolean, Date, DateTime, ForeignKey, Numeric, Text,
    text
)
from sqlalchemy.orm import relationship
from app.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'active'"))
    is_admin = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    payments = relationship("Payment", back_populates="user")


class Promotion(Base):
    __tablename__ = "promotions"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    discount_percent = Column(Integer, nullable=False, server_default=text("0"))
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, server_default=text("'active'"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    packages = relationship("Package", back_populates="promotion")
    payments = relationship("Payment", back_populates="promotion")


class Package(Base):
    __tablename__ = "packages"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    price_thb = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    credits = Column(Integer, nullable=False, server_default=text("0"))
    duration_days = Column(Integer, nullable=True)
    is_lifetime = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    status = Column(String(20), nullable=False, server_default=text("'active'"))
    # ✅ FK ไป promotions (nullable)
    promotion_id = Column(Integer, ForeignKey("promotions.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    promotion = relationship("Promotion", back_populates="packages")
    payments = relationship("Payment", back_populates="package")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    package_id = Column(Integer, ForeignKey("packages.id"), nullable=False)
    promotion_id = Column(Integer, ForeignKey("promotions.id"), nullable=True)
    total = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    status = Column(String(20), nullable=False, server_default=text("'pending'"))  # pending/approved/rejected
    slip_path = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    user = relationship("User", back_populates="payments")
    package = relationship("Package", back_populates="payments")
    promotion = relationship("Promotion", back_populates="payments")


# ถ้ามี CarCache อยู่เดิมแล้วไม่ต้องแก้; ถ้าจำเป็นจริง ๆ ควรคงเดิมไว้
# class CarCache(Base): ...
