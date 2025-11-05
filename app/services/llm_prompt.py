# app/services/llm_prompt.py
import json

def _val(x, default="N/A"):
    x = (x or "").strip() if isinstance(x, str) else x
    return x if x else default

def build_cars_payload(cars, max_items=40):
    """
    Convert CarCache list -> compact JSON structure for the LLM.
    """
    payload = []
    for i, c in enumerate(cars[:max_items], start=1):
        ex = c.extra or {}
        sp = ex.get("สเปกย่อย") or {}

        payload.append({
            "index": i,
            "car_id": c.id,
            "source": c.source,
            "title": c.title,
            "brand": c.brand or ex.get("ยี่ห้อ"),
            "model": c.model or ex.get("รุ่น") or ex.get("ชื่อรุ่น"),
            "trim": ex.get("รุ่นย่อย") or sp.get("รุ่นย่อย"),
            "year": c.year or ex.get("ปีรถ") or sp.get("ปีจดทะเบียน"),
            "price_thb": int(c.price_thb) if c.price_thb is not None else None,
            "mileage_km": c.mileage_km or ex.get("เลขไมล์") or ex.get("เลขไมล์(กม.)"),
            "fuel": ex.get("เชื้อเพลิง") or sp.get("เชื้อเพลิง"),
            "gear": ex.get("เกียร์") or sp.get("เกียร์"),
            "body_type": ex.get("ประเภทรถ") or ex.get("ประเภทย่อย") or sp.get("ประเภทรถ"),
            "color": ex.get("สี") or sp.get("สี"),
            "province_or_location": c.province or ex.get("ที่ตั้งรถ") or ex.get("จังหวัด"),
            "URL": c.url,
            "image_url": c.image_url,
        })
    return payload

def build_gemini_prompt(cars, form_params, exclude_ids=None):
    """
    exclude_ids: list of car_id that must not be selected (used when user asks for "another pick").
    """
    exclude_ids = exclude_ids or []

    q = form_params.get("q") or ""
    min_budget = form_params.get("min_budget") or 0
    gender = _val(form_params.get("gender"))
    marital = _val(form_params.get("marital_status"))
    occ = _val(form_params.get("occupation"))
    edu = _val(form_params.get("education_level"))
    salary = _val(form_params.get("salary"))
    car_type = form_params.get("car_type") or ""
    fuel_type = form_params.get("fuel_type") or ""
    gear_type = form_params.get("gear_type") or ""
    color = form_params.get("color") or ""
    purpose = _val(form_params.get("purpose"))
    other = _val(form_params.get("other_prefs"))

    cars_json = json.dumps(build_cars_payload(cars), ensure_ascii=False)

    prompt = f"""
You are a used-car advisor in Thailand. Your task is to choose **exactly one** "best-fit" car from the list below.
**Do not** fabricate information; follow these rules strictly.

[User Info]
- Query: {q or "N/A"}
- Minimum budget: {min_budget} THB
- Monthly income: {salary}
- Gender: {gender}
- Marital status: {marital}
- Occupation: {occ}
- Education: {edu}
- Specific preferences:
  - Body type: {car_type or "All"}
  - Fuel type: {fuel_type or "All"}
  - Transmission: {gear_type or "All"}
  - Color: {color or "All"}
- Primary usage: {purpose}
- Other preferences: {other}

[Do NOT select these car_id]: {exclude_ids if exclude_ids else "—"}

[Candidate cars] (index 1..N):
```json
{cars_json}
""".strip()
    return prompt
