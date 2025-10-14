# scripts/seed_packages_full.py
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.db import SessionLocal
from app.models import Package

app = create_app()

DATA = [
    dict(code="PKG_FREE",     name="Free Trial", credits=10,   duration_days=7,   is_lifetime=False, price_thb=0,    status="active"),
    dict(code="PKG_MINI",     name="Mini",       credits=10,   duration_days=7,   is_lifetime=False, price_thb=35,   status="active"),
    dict(code="PKG_BASIC",    name="Basic",      credits=50,   duration_days=30,  is_lifetime=False, price_thb=149,  status="active"),
    dict(code="PKG_EXPLORER", name="Explorer",   credits=150,  duration_days=30,  is_lifetime=False, price_thb=249,  status="active"),
    dict(code="PKG_MONTHLY",  name="Monthly",    credits=999999, duration_days=30, is_lifetime=False, price_thb=299, status="active"),
    dict(code="PKG_LIFETIME", name="Lifetime",   credits=999999, duration_days=None, is_lifetime=True, price_thb=3490, status="active"),
]

def run():
    s = SessionLocal()
    try:
        for data in DATA:
            row = s.query(Package).filter_by(code=data["code"]).first()
            if row:
                # อัปเดตค่าตาม DATA (upsert)
                for k, v in data.items():
                    setattr(row, k, v)
                print(f"Updated {data['code']}")
            else:
                s.add(Package(**data))
                print(f"Inserted {data['code']}")
        s.commit()
        print("Done. Total:", s.query(Package).count())
    finally:
        s.close()

if __name__ == "__main__":
    run()
