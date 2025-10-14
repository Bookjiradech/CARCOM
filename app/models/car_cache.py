# app/models/car_cache.py
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy.orm import Mapped, mapped_column, synonym
from sqlalchemy import BigInteger, String, Integer, Numeric, DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base  # ← ต้องอิมพอร์ต Base จากที่นี่เท่านั้น ห้าม from app.models import CarCache

class CarCache(Base):
    __tablename__ = "car_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # คอลัมน์จริงในตาราง
    source: Mapped[str] = mapped_column(String(50), nullable=False)   # เช่น 'kaidee'
    source_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[Optional[str]] = mapped_column(String(80))
    model: Mapped[Optional[str]] = mapped_column(String(120))
    year: Mapped[Optional[int]] = mapped_column(Integer)

    price_thb: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    mileage_km: Mapped[Optional[int]] = mapped_column(Integer)

    province: Mapped[Optional[str]] = mapped_column(String(80))  # ที่ตั้ง/จังหวัด
    url: Mapped[Optional[str]] = mapped_column(Text)             # ลิงก์ประกาศ
    image_url: Mapped[Optional[str]] = mapped_column(Text)

    extra: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)    # เก็บ raw attributes

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ---------- ALIASES (ไม่ต้องไมเกรตฐานข้อมูลเพิ่ม) ----------
    source_site: Mapped[str] = synonym("source")
    source_url:  Mapped[Optional[str]] = synonym("url")
    attrs_json:  Mapped[Optional[Dict[str, Any]]] = synonym("extra")
    location:    Mapped[Optional[str]] = synonym("province")
