# app/services/llm.py
import os, json, re
import google.generativeai as genai

def pick_best_car(params: dict, cars: list[dict]):
    """
    params: จาก SearchSession.params_json (dict)
    cars: list ของรถ (dict) ที่จะให้ LLM เลือก
    return: (best_index: int|None, reason: str|None, raw_text: str)
    """
    api = os.getenv("GEMINI_API_KEY")
    if not api:
        return None, None, "NO_API_KEY"

    genai.configure(api_key=api)
    model = genai.GenerativeModel("gemini-1.5-flash")

    # สร้าง list แบบย่อให้ LLM อ่านง่าย + มี 'index' เริ่ม 1
    brief = []
    for i, c in enumerate(cars, start=1):
        brief.append({
            "index": i,
            "title": c.get("title"),
            "brand": c.get("brand"),
            "model": c.get("model"),
            "year": c.get("year"),
            "mileage_km": c.get("mileage_km"),
            "price_thb": c.get("price_thb"),
            "fuel_type": c.get("fuel_type"),
            "transmission": c.get("transmission"),
        })

    system = (
        "คุณเป็นผู้ช่วยแนะนำรถมือสอง เลือก 1 คันที่เหมาะสมที่สุดจากรายการที่ให้ "
        "พิจารณาเงื่อนไขงบประมาณและบริบทผู้ใช้งาน"
    )

    # ขอผลแบบ JSON เพื่อลดปัญหาการแปลงผลลัพธ์
    prompt = {
        "params": params,
        "cars": brief,
        "instruction": (
            "โปรดส่งออกผลลัพธ์เป็น JSON เท่านั้น รูปแบบ:\n"
            "{ \"best_index\": <เลขลำดับ 1..N>, \"reason\": \"อธิบายเหตุผล >= 100 ตัวอักษร\" }"
        )
    }

    resp = model.generate_content(
        contents=[system, "ข้อมูล:", json.dumps(prompt, ensure_ascii=False)]
    )

    text = resp.text or ""
    # พยายามดึง JSON
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None, None, text

    try:
        data = json.loads(m.group(0))
        best = int(data.get("best_index")) if "best_index" in data else None
        reason = data.get("reason")
        # ปรับให้อยู่ในช่วง
        if best is not None and (best < 1 or best > len(cars)):
            best = None
        return best, reason, text
    except Exception:
        return None, None, text
