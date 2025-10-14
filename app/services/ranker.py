from __future__ import annotations
from typing import List, Dict, Any, Tuple
from decimal import Decimal

def _to_float(x):
    if x is None:
        return None
    if isinstance(x, Decimal):
        return float(x)
    try:
        return float(x)
    except Exception:
        return None

def rank_cars(cars: List[Any], profile: Dict[str, Any]) -> Tuple[List[Any], str]:
    """
    จัดอันดับแบบง่าย:
      - ใกล้งบเป้าหมาย (ใช้ max_budget ถ้ามี ไม่งั้นใช้ min_budget)
      - ปีใหม่กว่า ดีกว่า
      - ไมล์น้อยกว่า ดีกว่า
    """
    target = None
    if profile.get("max_budget"):
        target = _to_float(profile["max_budget"])
    elif profile.get("min_budget"):
        target = _to_float(profile["min_budget"])

    def score(c):
        price = _to_float(getattr(c, "price_thb", None)) or 10**12
        year  = getattr(c, "year", None) or 0
        mile  = getattr(c, "mileage_km", None) or 10**9
        diff  = abs(price - target) if target else price
        # ยิ่งคะแนนต่ำยิ่งดี
        return (diff, -year, mile)

    ranked = sorted(cars, key=score)
    explain = "เรียงจากรถที่ราคาใกล้งบประมาณมากที่สุด แล้วพิจารณาปีที่ใหม่กว่าและเลขไมล์ที่น้อยกว่า"
    return ranked, explain
