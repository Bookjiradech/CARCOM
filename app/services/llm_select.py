# app/services/llm_select.py
# -*- coding: utf-8 -*-
import os, json, re
from decimal import Decimal
from typing import List, Tuple, Optional

def _safe_int(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, Decimal):
        return int(v)  # strip fraction
    # extract only digits from strings, e.g., "519,000 THB"
    m = re.findall(r"\d+", str(v))
    return int("".join(m)) if m else None

def _serialize_car(c):
    ex = c.extra or {}
    sp = (ex.get("สเปกย่อย") or {}) if isinstance(ex.get("สเปกย่อย"), dict) else {}
    return {
        "id": c.id,
        "title": c.title,
        "brand": c.brand,
        "model": c.model,
        "year": _safe_int(getattr(c, "year", None)),
        "price_thb": _safe_int(getattr(c, "price_thb", None)),
        "mileage_km": _safe_int(getattr(c, "mileage_km", None)),
        "fuel": ex.get("เชื้อเพลิง") or sp.get("เชื้อเพลิง"),
        "gear": ex.get("เกียร์") or sp.get("เกียร์"),
        "source": getattr(c, "source", None) or getattr(c, "source_site", None),
        "url": getattr(c, "url", None),
        "province": getattr(c, "province", None) or ex.get("จังหวัด") or ex.get("ที่ตั้งรถ"),
        "image_url": getattr(c, "image_url", None),
    }

def _fallback_pick(cars: List, max_budget: Optional[int], exclude_ids: List[int]) -> Tuple[Optional[object], str]:
    # Choose the cheapest within budget and not in exclude; if none, choose the first viable one.
    candidates = []
    for c in cars:
        if exclude_ids and c.id in exclude_ids:
            continue
        p = _safe_int(getattr(c, "price_thb", None))
        if max_budget is not None and p is not None and p > max_budget:
            continue
        candidates.append((p if p is not None else 10**15, c))
    if not candidates:
        # Allow over-budget if nothing fits
        for c in cars:
            if exclude_ids and c.id in exclude_ids:
                continue
            p = _safe_int(getattr(c, "price_thb", None))
            candidates.append((p if p is not None else 10**15, c))
    if not candidates:
        return None, ""
    candidates.sort(key=lambda x: x[0])
    best = candidates[0][1]
    ptxt = f"{_safe_int(best.price_thb):,} THB" if _safe_int(best.price_thb) is not None else "N/A"
    return best, f"Picked the best-priced car within budget: {ptxt}"

def pick_best_car_with_gemini(
    cars: List,
    session_params: dict | None = None,
    exclude_ids: List[int] | None = None,
    fallback_first: bool = True
) -> Tuple[Optional[object], str]:
    """
    Return (car_obj, reason_en)
    - Uses Google GenAI SDK (google-genai).
    - If API is unavailable/errors, falls back to a deterministic rule.
    """
    session_params = session_params or {}
    exclude_ids = exclude_ids or []

    # Prepare payload for the model
    cars_payload = [_serialize_car(c) for c in cars if not (exclude_ids and c.id in exclude_ids)]
    max_budget = _safe_int(session_params.get("max_budget"))

    # IDs of cars within budget (for post-check)
    in_budget_ids = {
        cp["id"]
        for cp in cars_payload
        if (max_budget is None or (cp["price_thb"] is not None and cp["price_thb"] <= max_budget))
    }

    # If no API key, fallback immediately
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return _fallback_pick(cars, max_budget, exclude_ids)

    try:
        # ========== New SDK ==========
        # pip install -U google-genai
        from google import genai
        from google.genai import types  # GenerateContentConfig / schema

        # Reads GEMINI_API_KEY from env automatically
        client = genai.Client()

        # Force JSON output
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            # Optionally lock schema:
            # response_schema={
            #     "type": "object",
            #     "properties": {
            #         "car_id": {"type": "integer"},
            #         "reason": {"type": "string"}
            #     },
            #     "required": ["car_id", "reason"]
            # }
        )

        prompt = f"""
You are an assistant that selects **one** "best-fit used car" for a user.
Constraints:
- User's maximum budget (no more than): {max_budget if max_budget is not None else "N/A"}
- Candidates are provided as a JSON array in `cars_list` below.
- If there are cars within budget, consider only those first; otherwise consider all.

Criteria:
1) Value for money
2) Suitability to usage (refer to session_params if provided)
3) Lower mileage is better
4) Newer year is better

Numeric rules:
- Use only numbers that exist in the JSON
- Money is Thai Baht, format as ###,### THB
- If a number is missing, say "N/A"

Reply **JSON only**:
{{
  "car_id": <id>,
  "reason": "<English explanation, 80–180 words, cite only real numbers>"
}}

session_params:
{json.dumps({k: v for k, v in session_params.items() if k in ("q","max_budget","salary","gender","marital_status","occupation","education_level","purpose","other_prefs")}, ensure_ascii=False)}

cars_list:
{json.dumps(cars_payload, ensure_ascii=False)}
        """.strip()

        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=config,
        )

        txt = (resp.text or "").strip()

        # Try to parse JSON
        j = None
        try:
            j = json.loads(txt)
        except Exception:
            m = re.search(r"\{[\s\S]+\}", txt)
            if m:
                try:
                    j = json.loads(m.group(0))
                except Exception:
                    j = None

        if not isinstance(j, dict) or "car_id" not in j:
            # Bad format → fallback
            return _fallback_pick(cars, max_budget, exclude_ids)

        cid = _safe_int(j.get("car_id"))
        reason = str(j.get("reason") or "").strip()

        # Map back to object
        selected = None
        for c in cars:
            if c.id == cid and c.id not in exclude_ids:
                selected = c;
                break

        # If model picked over-budget while in-budget options exist → correct it
        if selected:
            price = _safe_int(getattr(selected, "price_thb", None))
            if max_budget is not None and in_budget_ids and selected.id not in in_budget_ids:
                fb, fb_reason = _fallback_pick(cars, max_budget, exclude_ids)
                if fb:
                    return fb, (reason or fb_reason)
            # Normalize price formatting inside reason
            if price is not None:
                reason = reason.replace(str(price), f"{price:,}")
        else:
            return _fallback_pick(cars, max_budget, exclude_ids)

        return selected, reason or "Reason: selected based on value within budget."

    except Exception as e:
        # Do not crash: log and fallback
        print("pick_best_car_with_gemini error:", e)
        return _fallback_pick(cars, max_budget, exclude_ids)
