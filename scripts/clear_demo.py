# scripts/clear_demo.py
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import or_
from app.db import SessionLocal
from app.models import CarCache

def main():
    db = SessionLocal()
    try:
        deleted = db.query(CarCache).filter(
            or_(CarCache.source == "demo", CarCache.source_site == "demo")
        ).delete(synchronize_session=False)
        db.commit()
        print("Deleted demo rows:", deleted)
    finally:
        db.close()

if __name__ == "__main__":
    main()
