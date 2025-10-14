# scripts/topup_credits.py
import sys, os
from datetime import datetime, timedelta

# ให้ Python เห็นโฟลเดอร์ app/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.db import SessionLocal
from app.models import User, Package, UserPackage

# โหลด config จาก .env ผ่าน create_app
app = create_app()

def topup(username: str, credits: int, days: int | None = None, pkg_code="PKG_ADMIN_TOPUP"):
    db = SessionLocal()
    try:
        # หา user
        user = db.query(User).filter_by(username=username).first()
        if not user:
            print(f"User '{username}' not found")
            return

        # หา/สร้าง package สำหรับท็อปอัพ
        pkg = db.query(Package).filter_by(code=pkg_code).first()
        if not pkg:
            pkg = Package(
                code=pkg_code,
                name="Admin Topup",
                credits=0,
                duration_days=None,
                is_lifetime=True,
                price_thb=0,
                status="active",
            )
            db.add(pkg)
            db.flush()

        # days เป็น 0 หรือ None = ไม่มีวันหมดอายุ
        end_at = None if not days or int(days) == 0 else datetime.utcnow() + timedelta(days=int(days))

        # เพิ่มเครดิตเป็นเรคคอร์ดใหม่
        up = UserPackage(
            user_id=user.id,
            package_id=pkg.id,
            remaining_calls=int(credits),
            end_at=end_at,
            status="active",
        )
        db.add(up)
        db.commit()
        print(f"OK: added {credits} credits to '{username}' (expires: {end_at or 'no expiry'})")
    finally:
        db.close()

if __name__ == "__main__":
    username = sys.argv[1] if len(sys.argv) > 1 else "oak"
    credits = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    topup(username, credits, days)
