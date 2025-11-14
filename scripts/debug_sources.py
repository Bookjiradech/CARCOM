# scripts/debug_sources.py
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from collections import Counter
from sqlalchemy import select

from app.db import SessionLocal
from app.models import CarCache

def main():
    db = SessionLocal()
    try:
        rows = db.execute(
            select(CarCache.source, CarCache.source_site, CarCache.title)
        ).all()
        counter = Counter()
        for src, site, title in rows:
            key = (src or site or "NONE")
            counter[key] += 1
        print("ALL sources in car_cache:", counter)
        print("Sample RODDONJAI rows:")
        q = db.execute(
            select(CarCache).where((CarCache.source == "roddonjai") | (CarCache.source_site == "roddonjai")).limit(5)
        ).scalars().all()
        for c in q:
            print("-", c.id, c.source, c.source_site, c.title, c.price_thb)
    finally:
        db.close()

if __name__ == "__main__":
    main()
