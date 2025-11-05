# app/services/credits.py
from sqlalchemy import select, func
from app.models import UserPackage

def consume_one_credit(db, user_id: int) -> bool:
    """
    Deduct 1 credit from an active package that still has credits > 0.
    Prefer the package that expires sooner first (smaller end_at first, NULL goes last).
    Returns True if deduction succeeded, False if there are not enough credits.
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
