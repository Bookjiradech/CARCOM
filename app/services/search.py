from sqlalchemy import select, func
from app.models import CarCache

def pick_cars(db, filters: dict | None, limit: int = 12):
    """
    เลือกรถจาก CarCache แบบง่าย ๆ: กรองตามงบ/ยี่ห้อ/ปี แล้ว random
    """
    stmt = select(CarCache)
    if filters:
        budget = (filters.get("budget_max") or "").strip()
        brand = (filters.get("brand") or "").strip()
        min_year = (filters.get("min_year") or "").strip()

        if budget.isdigit():
            stmt = stmt.where(CarCache.price_thb <= int(budget))
        if brand:
            stmt = stmt.where(CarCache.brand.ilike(f"%{brand}%"))
        if min_year.isdigit():
            stmt = stmt.where(CarCache.year >= int(min_year))

    stmt = stmt.order_by(func.random()).limit(limit)
    return db.execute(stmt).scalars().all()
