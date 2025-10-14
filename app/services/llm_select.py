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
        return int(v)  # ตัดเศษทิ้ง
    # ดึงเฉพาะตัวเลขจากสตริง เช่น "519,000 ฿"
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
    # เลือกคันที่ถูกที่สุดภายใต้งบและไม่อยู่ใน exclude; ถ้าไม่มี ให้เลือกคันแรก
    candidates = []
    for c in cars:
        if exclude_ids and c.id in exclude_ids:
            continue
        p = _safe_int(getattr(c, "price_thb", None))
        if max_budget is not None and p is not None and p > max_budget:
            continue
        candidates.append((p if p is not None else 10**15, c))
    if not candidates:
        # อนุญาตเกินงบ หากไม่มีจริงๆ
        for c in cars:
            if exclude_ids and c.id in exclude_ids:
                continue
            p = _safe_int(getattr(c, "price_thb", None))
            candidates.append((p if p is not None else 10**15, c))
    if not candidates:
        return None, ""
    candidates.sort(key=lambda x: x[0])
    best = candidates[0][1]
    ptxt = f"{_safe_int(best.price_thb):,} ฿" if _safe_int(best.price_thb) is not None else "ไม่ระบุ"
    return best, f"เลือกคันราคาดีที่สุดภายใต้งบประมาณ: {ptxt}"

def pick_best_car_with_gemini(
    cars: List,
    session_params: dict | None = None,
    exclude_ids: List[int] | None = None,
    fallback_first: bool = True
) -> Tuple[Optional[object], str]:
    """
    คืน (car_obj, reason_th)
    - ใช้ Google GenAI SDK (google-genai)
    - ถ้า API ใช้ไม่ได้/ผิดพลาด จะ fallback เป็นกติกา deterministic
    """
    session_params = session_params or {}
    exclude_ids = exclude_ids or []

    # เตรียม payload ให้โมเดล
    cars_payload = [_serialize_car(c) for c in cars if not (exclude_ids and c.id in exclude_ids)]
    max_budget = _safe_int(session_params.get("max_budget"))

    # set ของรถที่ "อยู่ในงบ" เพื่อใช้ตรวจภายหลัง
    in_budget_ids = {
        cp["id"]
        for cp in cars_payload
        if (max_budget is None or (cp["price_thb"] is not None and cp["price_thb"] <= max_budget))
    }

    # ถ้าไม่มี API key ก็ fallback ไปเลย
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return _fallback_pick(cars, max_budget, exclude_ids)

    try:
        # ========== ใช้ SDK ใหม่ ==========
        # pip install -U google-genai
        from google import genai
        from google.genai import types  # GenerateContentConfig / schema

        # จะอ่าน GEMINI_API_KEY จาก env อัตโนมัติ
        client = genai.Client()

        # เปิด JSON mode เพื่อบังคับให้ตอบเป็น JSON
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            # หากต้องการล็อกโครงสร้าง JSON ให้แน่นอนยิ่งขึ้น เปิดคอมเมนต์ข้างล่างได้
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
คุณเป็นผู้ช่วยเลือก "รถมือสองที่เหมาะสมที่สุด" สำหรับผู้ใช้คนหนึ่ง
โจทย์:
- ผู้ใช้มีงบประมาณสูงสุด (ไม่เกิน): {max_budget if max_budget is not None else "ไม่ระบุ"}
- ตัวเลือกเป็นรายการ JSON ในตัวแปร cars_list ด้านล่าง
- ถ้ามีรถในงบ ให้พิจารณาเฉพาะรถที่ราคาไม่เกินงบก่อน แต่ถ้าไม่มีเลย ให้พิจารณาทุกคัน

เกณฑ์:
1) ความคุ้มค่า/ราคา
2) ความเหมาะกับการใช้งาน (อ้างอิง session_params หากมี)
3) ไมล์น้อยเป็นบวก
4) ปีใหม่เป็นบวก

ข้อกำหนดตัวเลข:
- ใช้เฉพาะตัวเลขจาก JSON เท่านั้น
- เงินเป็นบาทไทย ฟอร์แมต ###,### ฿
- ถ้าไม่มีตัวเลข ให้ใช้คำว่า "ไม่ระบุ"

ให้ตอบกลับเป็น JSON เท่านั้น:
{{
  "car_id": <id>,
  "reason": "<เหตุผลภาษาไทย 80–180 คำ อ้างตัวเลขจริงเท่านั้น>"
}}

session_params:
{json.dumps({k: v for k, v in session_params.items() if k in ("q","max_budget","salary","gender","marital_status","occupation","education_level","purpose","other_prefs")}, ensure_ascii=False)}

cars_list:
{json.dumps(cars_payload, ensure_ascii=False)}
        """.strip()

        # เรียกด้วยรูปแบบใหม่
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=config,
        )

        txt = (resp.text or "").strip()

        # พยายาม parse JSON (เพราะเราเปิด JSON mode ไว้)
        j = None
        try:
            j = json.loads(txt)
        except Exception:
            # กันกรณีห่อโค้ดบล็อก
            m = re.search(r"\{[\s\S]+\}", txt)
            if m:
                try:
                    j = json.loads(m.group(0))
                except Exception:
                    j = None

        if not isinstance(j, dict) or "car_id" not in j:
            # ผิดฟอร์แมต → fallback
            return _fallback_pick(cars, max_budget, exclude_ids)

        cid = _safe_int(j.get("car_id"))
        reason = str(j.get("reason") or "").strip()

        # map กลับไปเป็น object จริง
        selected = None
        for c in cars:
            if c.id == cid and c.id not in exclude_ids:
                selected = c
                break

        # ถ้าโมเดลเลือกคันเกินงบ ทั้งที่มีคันในงบ → แก้ให้
        if selected:
            price = _safe_int(getattr(selected, "price_thb", None))
            if max_budget is not None and in_budget_ids and selected.id not in in_budget_ids:
                fb, fb_reason = _fallback_pick(cars, max_budget, exclude_ids)
                if fb:
                    return fb, (reason or fb_reason)
            # ทำความสะอาดตัวเลขใน reason ให้เป็นรูป ###,### ฿ สำหรับราคาที่เลือกได้
            if price is not None:
                reason = reason.replace(str(price), f"{price:,}")
        else:
            return _fallback_pick(cars, max_budget, exclude_ids)

        return selected, reason or "เหตุผล: เลือกจากเกณฑ์ความคุ้มค่าภายใต้งบประมาณ"

    except Exception as e:
        # ไม่ให้ระบบล่ม: log แล้ว fallback
        print("pick_best_car_with_gemini error:", e)
        return _fallback_pick(cars, max_budget, exclude_ids)
