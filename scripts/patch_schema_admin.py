# scripts/patch_schema_admin.py
import os, sys
from dotenv import load_dotenv
from sqlalchemy import text

# ให้ import app.* ได้
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv()

from app.db import engine  # ใช้ engine ของโปรเจ็กต์

DDL_STMTS = [
    # users.updated_at
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",

    # payments.updated_at + promotion_id
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS promotion_id BIGINT",

    # packages.promotion_id
    "ALTER TABLE packages ADD COLUMN IF NOT EXISTS promotion_id BIGINT",
]

FK_QUERIES = [
    # FK: payments.promotion_id -> promotions.id
    (
        "fk_payments_promo",
        "ALTER TABLE payments ADD CONSTRAINT fk_payments_promo "
        "FOREIGN KEY (promotion_id) REFERENCES promotions(id) ON DELETE SET NULL"
    ),
    # FK: packages.promotion_id -> promotions.id
    (
        "fk_packages_promo",
        "ALTER TABLE packages ADD CONSTRAINT fk_packages_promo "
        "FOREIGN KEY (promotion_id) REFERENCES promotions(id) ON DELETE SET NULL"
    ),
]

def fk_exists(conn, name: str) -> bool:
    sql = text("SELECT 1 FROM pg_constraint WHERE conname = :name")
    return conn.execute(sql, {"name": name}).scalar() is not None

def main():
    with engine.begin() as conn:
        # 1) เพิ่มคอลัมน์ (idempotent)
        for stmt in DDL_STMTS:
            conn.execute(text(stmt))
            print("OK:", stmt)

        # 2) เพิ่ม FK ถ้ายังไม่มี
        for fk_name, fk_stmt in FK_QUERIES:
            if not fk_exists(conn, fk_name):
                conn.execute(text(fk_stmt))
                print("OK (FK added):", fk_name)
            else:
                print("SKIP (FK exists):", fk_name)

    print("✅ Schema patch complete.")

if __name__ == "__main__":
    main()
