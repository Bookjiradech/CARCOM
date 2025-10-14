import os, sys
from sqlalchemy import text
from dotenv import load_dotenv

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))

from app.db import SessionLocal  # ใช้ Base/Session ของแอพ

def make_admin(username: str):
    db = SessionLocal()
    try:
        db.execute(text("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS is_admin boolean
        """))
        db.execute(text("UPDATE users SET is_admin = false WHERE is_admin IS NULL"))
        db.execute(text("ALTER TABLE users ALTER COLUMN is_admin SET DEFAULT false"))
        db.execute(text("ALTER TABLE users ALTER COLUMN is_admin SET NOT NULL"))
        res = db.execute(text("UPDATE users SET is_admin = true WHERE username = :u"), {"u": username})
        db.commit()
        if res.rowcount == 0:
            print(f"⚠️ ไม่พบผู้ใช้ '{username}'")
        else:
            print(f"✅ ตั้ง '{username}' เป็นแอดมินเรียบร้อย")
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts\\make_admin.py <username>")
        sys.exit(1)
    make_admin(sys.argv[1])
