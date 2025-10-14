# app/services/credits.py
from sqlalchemy import select, func
from app.models import UserPackage

def consume_one_credit(db, user_id: int) -> bool:
    """
    ตัดเครดิต 1 หน่วยจากแพ็กเกจที่ยัง active และมีเครดิต > 0
    เลือกใช้แพ็กเกจที่ 'ใกล้หมดอายุ' ก่อน (end_at น้อยก่อน, NULL ไปท้ายสุด)
    คืนค่า True ถ้าตัดสำเร็จ, False ถ้าเครดิตไม่พอ
    """
    q = (
        select(UserPackage)
        .where(
            UserPackage.user_id == user_id,
            UserPackage.status == "active",
            (UserPackage.end_at.is_(None)) | (UserPackage.end_at > func.now()),
            UserPackage.remaining_calls > 0,
        )
        .order_by(UserPackage.end_at.asc().nulls_last())
    )
    up = db.execute(q).scalars().first()
    if not up:
        return False

    up.remaining_calls -= 1
    db.add(up)
    return True
