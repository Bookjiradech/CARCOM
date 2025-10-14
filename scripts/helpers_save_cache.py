# scripts/helpers_save_cache.py
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from sqlalchemy import select
from app import create_app
from app.db import SessionLocal
from app.models import CarCache

app = create_app()

def upsert_car(db, data: dict):
    """
    data ต้องมีอย่างน้อย: source, external_id
    ฟิลด์ที่แนะนำ:
      title, brand, model, year, mileage_km, price_thb,
      fuel_type, transmission, province, url, image_url
    """
    row = db.execute(
        select(CarCache).where(
            CarCache.source == data["source"],
            CarCache.external_id == data["external_id"]
        )
    ).scalar_one_or_none()

    if row:
        # อัปเดตข้อมูลที่เปลี่ยนบ่อย
        for k in ["title","brand","model","year","mileage_km","price_thb","fuel_type",
                  "transmission","province","url","image_url"]:
            if k in data and data[k] is not None:
                setattr(row, k, data[k])
        db.add(row)
    else:
        db.add(CarCache(**data))
