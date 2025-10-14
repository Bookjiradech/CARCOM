# scripts/seed_packages.py
from app import create_app
from app.db import SessionLocal
from app.models import Package

app = create_app()

def run():
    db = SessionLocal()
    try:
        data = [
            dict(code="PKG_MINI", name="Mini", credits=10,  duration_days=7,  is_lifetime=False, price_thb=35),
            dict(code="PKG_BASIC", name="Basic", credits=50, duration_days=30, is_lifetime=False, price_thb=149),
            dict(code="PKG_LIFE", name="Lifetime", credits=999999, duration_days=0, is_lifetime=True,  price_thb=3490),
        ]
        for d in data:
            if not db.query(Package).filter_by(code=d["code"]).first():
                db.add(Package(**d))
        db.commit()
        print("Seed packages OK")
    finally:
        db.close()

if __name__ == "__main__":
    run()
