# -*- coding: utf-8 -*-
# scripts/add_promotion_id_to_packages.py

import os, sys
# ให้ import app.* ได้ไม่ว่าจะรันจากไหน
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
from sqlalchemy import text
from app.db import SessionLocal

SQLS = [
    # 1) เพิ่มคอลัมน์ ถ้ายังไม่มี
    """
    ALTER TABLE packages
    ADD COLUMN IF NOT EXISTS promotion_id INTEGER;
    """,
    # 2) เพิ่ม Foreign Key ถ้ายังไม่มี
    """
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'packages_promotion_id_fkey'
      ) THEN
        ALTER TABLE packages
        ADD CONSTRAINT packages_promotion_id_fkey
        FOREIGN KEY (promotion_id) REFERENCES promotions(id) ON DELETE SET NULL;
      END IF;
    END $$;
    """
]

def main():
    # โหลด .env (ถ้าใช้ DATABASE_URL จากไฟล์นี้)
    load_dotenv()

    db = SessionLocal()
    try:
        for s in SQLS:
            db.execute(text(s))
        db.commit()
        print("✅ Done: added packages.promotion_id (with FK if missing).")
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()
