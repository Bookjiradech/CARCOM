# app/services/llm_prompt.py
import json

def _val(x, default="ไม่ระบุ"):
    x = (x or "").strip() if isinstance(x, str) else x
    return x if x else default

def build_cars_payload(cars, max_items=40):
    """
    แปลงรายการ CarCache -> โครง JSON ที่กะทัดรัดสำหรับ LLM
    """
    payload = []
    for i, c in enumerate(cars[:max_items], start=1):
        ex = c.extra or {}
        sp = ex.get("สเปกย่อย") or {}

        payload.append({
            "ลำดับ": i,
            "car_id": c.id,
            "แหล่ง": c.source,
            "ชื่อ/หัวข้อ": c.title,
            "ยี่ห้อ": c.brand or ex.get("ยี่ห้อ"),
            "รุ่น": c.model or ex.get("รุ่น") or ex.get("ชื่อรุ่น"),
            "รุ่นย่อย": ex.get("รุ่นย่อย") or sp.get("รุ่นย่อย"),
            "ปี": c.year or ex.get("ปีรถ") or sp.get("ปีจดทะเบียน"),
            "ราคา(บาท)": int(c.price_thb) if c.price_thb is not None else None,
            "เลขไมล์(กม.)": c.mileage_km or ex.get("เลขไมล์") or ex.get("เลขไมล์(กม.)"),
            "เชื้อเพลิง": ex.get("เชื้อเพลิง") or sp.get("เชื้อเพลิง"),
            "เกียร์": ex.get("เกียร์") or sp.get("เกียร์"),
            "ประเภทรถ": ex.get("ประเภทรถ") or ex.get("ประเภทย่อย") or sp.get("ประเภทรถ"),
            "สี": ex.get("สี") or sp.get("สี"),
            "จังหวัด/ที่ตั้ง": c.province or ex.get("ที่ตั้งรถ") or ex.get("จังหวัด"),
            "URL": c.url,
            "รูปภาพ": c.image_url,
        })
    return payload

def build_gemini_prompt(cars, form_params, exclude_ids=None):
    """
    exclude_ids: รายการ car_id ที่ไม่ให้เลือก (เวลาผู้ใช้กด 'ค้นหาใหม่')
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
คุณคือที่ปรึกษาเลือกซื้อรถมือสองในประเทศไทย มีหน้าที่เลือก "รถที่เหมาะที่สุด" เพียง 1 คันจากรายการด้านล่าง
**ห้าม** สร้างข้อมูลที่ไม่มีในรายการ และต้องยึดกฎต่อไปนี้:

[ข้อมูลผู้ใช้]
- คำค้นหา: {q or "ไม่ระบุ"}
- งบขั้นต่ำ: {min_budget} บาท
- รายได้ต่อเดือน: {salary}
- เพศ: {gender}
- สถานภาพสมรส: {marital}
- อาชีพ: {occ}
- ระดับการศึกษา: {edu}
- ความต้องการเฉพาะ:
  - ประเภทรถ: {car_type or "ทั้งหมด"}
  - เชื้อเพลิง: {fuel_type or "ทั้งหมด"}
  - เกียร์: {gear_type or "ทั้งหมด"}
  - สี: {color or "ทั้งหมด"}
- การใช้งานหลัก: {purpose}
- ความต้องการอื่น ๆ: {other}

[ห้ามเลือก car_id ต่อไปนี้]: {exclude_ids if exclude_ids else "—"}

[รายการรถที่ให้พิจารณา] (ลำดับที่ 1..N):
```json
{cars_json}""".strip()