# app/services/translator.py
# -*- coding: utf-8 -*-
import os, json, re
from datetime import datetime
from threading import RLock

# path ไฟล์แคช (เปลี่ยนได้ผ่าน env)
CACHE_PATH = os.getenv("TRANSLATE_CACHE_PATH", os.path.join("data", "translate_cache.json"))

_lock = RLock()
_cache = None  # lazy load

KEY_MAP = {
    "ชื่อประกาศ": "title",
    "ยี่ห้อ": "brand",
    "รุ่น": "model",
    "รุ่นย่อย": "submodel",
    "ปีรถ": "year",
    "ปี": "year",
    "ราคา": "price",
    "เลขไมล์": "mileage_km",
    "เชื้อเพลิง": "fuel",
    "ประเภทเชื้อเพลิง": "fuel",
    "เกียร์": "gear",
    "ประเภทรถ": "body_type",
    "สี": "color",
    "จังหวัด": "province",
    "ที่อยู่": "province",
    "ตำแหน่ง": "province",
    "รูปภาพ": "image_url",
    "ลิงก์": "url",
}

EN_FIELDS = ["title","brand","model","submodel","province","color","fuel","gear","body_type"]

def _ensure_cache_loaded():
    global _cache
    if _cache is not None:
        return
    with _lock:
        if _cache is not None:
            return
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        if os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH, "r", encoding="utf-8") as f:
                    _cache = json.load(f)
            except Exception:
                _cache = {}
        else:
            _cache = {}

def _save_cache():
    with _lock:
        try:
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(_cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass  # ไม่ให้ล่มเพราะแคช

def normalize_keys_th_en(d: dict) -> dict:
    d = dict(d or {})
    raw = dict(d)
    norm = {}
    for k, v in raw.items():
        en_key = KEY_MAP.get(k, k)
        norm[en_key] = v
    d["_raw"] = raw
    d["_norm"] = norm
    return d

def _is_numberish(t: str) -> bool:
    return bool(re.fullmatch(r"[0-9,.\s]+(?:฿|บาท)?", t or ""))

def translate_text_th_en(text: str) -> str:
    """
    แปลไทย->อังกฤษ ด้วยไฟล์แคชก่อน ถ้าไม่เจอค่อยเรียก Gemini
    (ตั้ง env GEMINI_API_KEY ไว้แล้ว)
    """
    t = (text or "").strip()
    if not t or _is_numberish(t):
        return t

    _ensure_cache_loaded()
    with _lock:
        if t in _cache:
            return _cache[t]

    # --- เรียกโมเดล (เปลี่ยนเป็น Google Cloud Translate ก็ได้) ---
    from google import genai
    client = genai.Client()  # ใช้ GEMINI_API_KEY จาก env
    prompt = f"Translate to natural English for used-car listing context. Text: {t}"
    try:
        resp = client.models.generate_content(model="gemini-2.0-flash-lite", contents=prompt)
        out = (resp.text or t).strip()
    except Exception:
        out = t  # เซฟโหมด: ถ้าแปลไม่ได้ ให้คืนคำเดิม

    with _lock:
        _cache[t] = out
        _save_cache()
    return out

def enrich_with_en_values(d: dict) -> dict:
    """
    เติม _en เฉพาะฟิลด์สำคัญจาก _norm/_raw โดยใช้ file-cache
    """
    d = dict(d or {})
    norm = d.get("_norm") or {}
    en = dict(d.get("_en") or {})

    for k in EN_FIELDS:
        src = en.get(k) or norm.get(k) or d.get(k)
        if isinstance(src, str) and src.strip():
            en[k] = translate_text_th_en(src)

    d["_en"] = en
    # บันทึก timestamp ไว้หน่อย เผื่อดีบัก
    meta = d.get("_meta") or {}
    meta["translated_at"] = datetime.utcnow().isoformat() + "Z"
    d["_meta"] = meta
    return d

def prefer_en(d: dict, key: str, *fallback_keys: str):
    en = ((d.get("_en") or {}).get(key))
    if isinstance(en, str) and en.strip():
        return en.strip()
    for k in (key, *fallback_keys):
        v = (d.get("_norm") or {}).get(k) or d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None
