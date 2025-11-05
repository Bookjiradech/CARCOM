# app/services/translator.py
from __future__ import annotations
import os, json, re, hashlib, threading
from typing import Dict, Any, Iterable, Optional

# ---------- simple file cache ----------
_CACHE_PATH = os.path.join(os.getcwd(), "tmp_translate_cache.json")
_LOCK = threading.Lock()
_try_load = {}
if os.path.exists(_CACHE_PATH):
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            _try_load = json.load(f)
    except Exception:
        _try_load = {}
_CACHE: Dict[str, str] = dict(_try_load)

def _keyhash(text: str, src: str, tgt: str, backend: str) -> str:
    h = hashlib.sha256(f"{backend}|{src}->{tgt}|{text}".encode("utf-8")).hexdigest()
    return h

def _cache_get(text: str, src: str, tgt: str, backend: str) -> Optional[str]:
    return _CACHE.get(_keyhash(text, src, tgt, backend))

def _cache_put(text: str, src: str, tgt: str, backend: str, out: str):
    with _LOCK:
        _CACHE[_keyhash(text, src, tgt, backend)] = out
        try:
            os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
            with open(_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(_CACHE, f, ensure_ascii=False)
        except Exception:
            pass

# ---------- backends ----------
def _translate_gemini(texts: Iterable[str], source="th", target="en") -> list[str]:
    # ใช้ Gemini (คุณมี GEMINI_API_KEY อยู่แล้ว)
    from google import genai
    client = genai.Client()  # ใช้ env GEMINI_API_KEY อัตโนมัติ
    # แปลทีละก้อน (รวบ batch เพื่อลดค่าใช้จ่าย/latency)
    out = []
    for t in texts:
        if not t or re.fullmatch(r"\s*", t): 
            out.append(t); continue
        # cache
        c = _cache_get(t, source, target, "gemini")
        if c is not None:
            out.append(c); continue
        prompt = f"Translate into {target.upper()} only, no extra words:\n{t}"
        resp = client.models.generate_content(model="gemini-2.0-flash-lite", contents=prompt)
        txt = (resp.text or "").strip()
        _cache_put(t, source, target, "gemini", txt)
        out.append(txt)
    return out

def _translate_gcloud(texts: Iterable[str], source="th", target="en") -> list[str]:
    # ต้องตั้ง GOOGLE_APPLICATION_CREDENTIALS ล่วงหน้า
    from google.cloud import translate_v2 as translate
    client = translate.Client()
    outs = client.translate(list(texts), source_language=source, target_language=target, format_="text")
    res = []
    for i, t in enumerate(texts):
        if not t or re.fullmatch(r"\s*", t):
            res.append(t); continue
        tr = outs[i]["translatedText"]
        _cache_put(t, source, target, "gcloud", tr)
        res.append(tr)
    return res

# ---------- public API ----------
def translate_texts(texts: list[str], backend="gemini", source="th", target="en") -> list[str]:
    if backend == "gcloud":
        return _translate_gcloud(texts, source, target)
    return _translate_gemini(texts, source, target)

# คีย์ที่ “ควรแปลค่า” หากเป็นสตริงภาษาไทยจากหลายเว็บ
VALUE_FIELDS_TO_TRANSLATE = {
    "title","seller","province","location","color","body_type",
    # free-form in extra:
    "รุ่นย่อย","สเปก","หมายเหตุ","รายละเอียด","ที่ตั้งรถ","ประเภทรถ","สี","เชื้อเพลิง","เกียร์",
}

# แผนที่คีย์ไทย -> คีย์อังกฤษ (รวมจากทุกเว็บเท่าที่ใช้ร่วม)
KEY_MAP = {
    "ราคา":"price", "ผู้ขาย":"seller", "รูปภาพ":"image_url", "ชื่อประกาศ":"title",
    "ยี่ห้อ":"brand","รุ่น":"model","รุ่นย่อย":"trim","ปีรถ":"year","ปี":"year",
    "เลขไมล์":"mileage_km","เลขไมล์(กม.)":"mileage_km", "เชื้อเพลิง":"fuel",
    "ประเภทเชื้อเพลิง":"fuel","เกียร์":"transmission","ประเภทรถ":"body_type",
    "ประเภทย่อย":"body_type","สี":"color","ที่อยู่":"location","ตำแหน่ง":"location",
    "จังหวัด":"province","ลิงก์":"url","URL":"url"
}

def normalize_keys_th_en(d: Dict[str, Any]) -> Dict[str, Any]:
    """รวมคีย์ไทยให้เป็นอังกฤษเท่าที่รู้จัก (คงคีย์ที่ไม่รู้จักไว้)"""
    out = {}
    for k, v in (d or {}).items():
        out[KEY_MAP.get(k, k)] = v
    return out

def translate_record_values(d: Dict[str, Any], backend="gemini") -> Dict[str, Any]:
    """
    แปลเฉพาะ 'ค่า' ที่เป็นสตริง (ไทย->อังกฤษ) ทั้งในคีย์หลักและใน extra อื่น ๆ
    เก็บผลภาษาอังกฤษซ้อนใน _en เพื่ออ้างต่อได้
    """
    if not d: 
        return d
    # เตรียมรายการข้อความที่จะส่งแปล
    items_to_translate: list[tuple[list, str]] = []  # (pointer_chain, original_text)
    def walk(prefix: list, obj: Any):
        if isinstance(obj, dict):
            for kk, vv in obj.items():
                walk(prefix+[kk], vv)
        elif isinstance(obj, list):
            for i, vv in enumerate(obj):
                walk(prefix+[i], vv)
        elif isinstance(obj, str):
            keyname = str(prefix[-1]) if prefix else ""
            if keyname in VALUE_FIELDS_TO_TRANSLATE or re.search(r"[ก-๙]", obj):
                items_to_translate.append((prefix, obj))
    walk([], d)

    texts = [t for _, t in items_to_translate]
    if texts:
        translated = translate_texts(texts, backend=backend, source="th", target="en")
        # ใส่ผลลงไปใน d["_en"] แบบโครงสร้างเดียวกัน
        def set_in(out: dict, chain: list, value: Any):
            cur = out
            for c in chain[:-1]:
                cur = cur.setdefault(c, {} if isinstance(c, str) else {})
            cur[chain[-1]] = value
        en_out: dict = {}
        for (chain, _orig), tr in zip(items_to_translate, translated):
            set_in(en_out, chain, tr)
        d = dict(d)  # copy
        d["_en"] = en_out
    return d
