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
    Simple ranking:
      - Closest to target budget (use max_budget if present, otherwise min_budget)
      - Newer year is better
      - Lower mileage is better
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
        # Lower score is better
        return (diff, -year, mile)

    ranked = sorted(cars, key=score)
    explain = "Sorted by price closest to the target budget, then by newer year and lower mileage."
    return ranked, explain
