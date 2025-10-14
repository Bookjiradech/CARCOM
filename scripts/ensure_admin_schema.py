# backend/scripts/ensure_admin_schema.py
import os, sys
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.db import engine

SQLS = [
    "ALTER TABLE packages   ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false;",
    "ALTER TABLE promotions ADD COLUMN IF NOT EXISTS is_deleted boolean NOT NULL DEFAULT false;",
    "ALTER TABLE packages   ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();",
    "ALTER TABLE packages   ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();",
    "ALTER TABLE promotions ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();",
    "ALTER TABLE promotions ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();",
    "ALTER TABLE payments   ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();",
    "ALTER TABLE payments   ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();",

    "ALTER TABLE packages ADD COLUMN IF NOT EXISTS promotion_id integer;",
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
    """,
]

if __name__ == "__main__":
    with engine.begin() as conn:
        for sql in SQLS:
            conn.execute(text(sql))
    print("✅ ensured admin schema (packages/promotions/payments columns present).")
