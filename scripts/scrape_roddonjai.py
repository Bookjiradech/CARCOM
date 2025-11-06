# -*- coding: utf-8 -*-
"""
Scrape RodDonJai แล้ว upsert เข้า car_cache

ตัวอย่าง:
  python scripts\scrape_roddonjai.py --q "City" --min 0 --max 999999999 --limit 40 --chromedriver "C:\ScrapingCar\chromedriver.exe" --headless --debug-fuel --debug-print
"""

import os, sys, re, time, argparse, json
from typing import Optional, Dict, List, Tuple
from urllib.parse import urljoin
from dotenv import load_dotenv

# ให้ import app.* ได้
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from app.db import SessionLocal
from app.models import CarCache

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_URL = "https://www.roddonjai.com/"
LIST_INPUT_CSS = 'input[placeholder="ค้นหารถโดยยี่ห้อ, รุ่น, ชื่อดีลเลอร์"]'

# ----------------- utils -----------------
def load_env():
    load_dotenv()

def to_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    s = re.sub(r"[^\d]", "", str(s))
    return int(s) if s else None

def clean_money(txt: str) -> str:
    return re.sub(r"[^\d,\.]", "", txt or "").strip()

def build_driver(chromedriver_path: Optional[str], headless: bool):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1440,900")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
    if chromedriver_path:
        service = Service(chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)
    return driver

def wait_any(driver, selectors: List[str], timeout=20):
    conds = [EC.presence_of_element_located((By.CSS_SELECTOR, sel)) for sel in selectors]
    WebDriverWait(driver, timeout).until(lambda d: any(c(d) for c in conds))

def auto_scroll(driver, rounds=10, delay=1.0):
    last_h = 0
    for _ in range(rounds):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(delay)
        new_h = driver.execute_script("return document.body.scrollHeight;")
        if new_h == last_h:
            break
        last_h = new_h
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.2)

def abs_url(driver, u: str) -> str:
    return urljoin(driver.current_url, u or "")

def _all_words_in(text: str, q: str) -> bool:
    q = (q or "").strip().lower()
    words = [w for w in re.split(r"\s+", q) if w]
    if not words:
        return True
    blob = (text or "").lower()
    return all(w in blob for w in words)

# ----------------- list page -----------------
def is_rdj_car_url(href: str) -> bool:
    if not href: return False
    href = re.sub(r"[#?].*$", "", href)
    return "/service/car-detail/" in href

def collect_links(driver, limit: int, q: Optional[str] = None) -> List[str]:
    seen, links = set(), []
    try:
        cards = driver.find_elements(By.CSS_SELECTOR, 'a[href^="/service/car-detail/"]')
        for a in cards:
            try:
                href = a.get_attribute("href") or a.get_attribute("data-href") or ""
                if not href:
                    href = a.get_attribute("href") or ""
                if not href:
                    continue
                u = abs_url(driver, href)
                u = re.sub(r"[#?].*$", "", u).rstrip("/")
                if not is_rdj_car_url(u):
                    continue
                # กรองคำค้นขั้นต้นจากข้อความบนการ์ด
                if q:
                    txt = a.text.strip()
                    if not _all_words_in(txt + " " + u, q):
                        continue
                if u not in seen:
                    links.append(u); seen.add(u)
            except Exception:
                continue
    except Exception:
        pass

    # เผื่อไม่ครบ ลองดึงจาก page_source
    if len(links) < limit:
        html = driver.page_source
        for h in re.findall(r'href="([^"]+)"', html):
            u = abs_url(driver, h)
            u = re.sub(r"[#?].*$", "", u).rstrip("/")
            if is_rdj_car_url(u) and u not in seen:
                links.append(u); seen.add(u)
            if len(links) >= limit * 2:
                break

    return links[:limit]

def extract_year(text: str) -> Optional[int]:
    m = re.search(r"(\d{4})", text or "")
    try:
        y = int(m.group(1)) if m else None
        if y and 1980 <= y <= 2100:
            return y
    except Exception:
        pass
    return None

# ----------------- parse page -----------------
def parse_detail(driver, url: str, debug_fuel: bool=False) -> Dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(driver.page_source, "html.parser")

    def sel_text(selector, default=""):
        el = soup.select_one(selector)
        return (el.get_text(strip=True) if el else default) or default

    # --------- title / price / mileage / seller / province ----------
    title = sel_text('.css-ldavcx p') or sel_text('h1,h2,.jss420') or "ไม่พบชื่อรุ่น"

    price_txt = sel_text('p.MuiTypography-subtitle1.jss275') \
        or sel_text('.css-1sgkmcp ~ div p.MuiTypography-subtitle1')
    price_clean = clean_money(price_txt) if price_txt else ""
    price_int = to_int(price_clean)

    mileage_summary = sel_text('.css-j7qwjs p.MuiTypography-body1')  # เช่น “20,509 กม.”
    mil = re.search(r"([\d,]+)", mileage_summary or "")
    mileage_km = to_int(mil.group(1)) if mil else None

    seller = sel_text('p.MuiTypography-root.css-12zbq1l')
    province = sel_text('p.css-1ijcpbd')

    # --------- specs table ----------
    specs: Dict[str, str] = {}
    for row in soup.select('.MuiCollapse-wrapperInner .MuiGrid-item .d-flex.justify-content-between.mb-1'):
        k_el = row.select_one('p.w-50:nth-of-type(1)')
        v_el = row.select_one('p.w-50:nth-of-type(2)')
        k = k_el.get_text(strip=True) if k_el else ""
        v = v_el.get_text(strip=True) if v_el else ""
        if k and v:
            specs[k] = v
    # เผื่อไมล์หาย ใส่ซ้ำ
    if mileage_km and "เลขไมล์" not in specs:
        specs["เลขไมล์"] = f"{mileage_km:,} กม."

    # --------- brand / model / year heuristic ----------
    # 1) ใช้ในตารางก่อน
    brand = specs.get("ยี่ห้อ") or ""
    model = specs.get("รุ่น") or ""
    # 2) ถ้ายังว่าง ลองแยกจาก title
    if not brand or not model:
        m = re.match(r"([A-Za-zก-ฮ]+)\s+(.+)", title)
        if m:
            brand = brand or m.group(1)
            model = model or m.group(2)
    year = extract_year(specs.get("ปีรถ") or specs.get("ปีจดทะเบียน") or title)

    # --------- image (เลือกอันที่เป็น WATERMARK ก่อน) ----------
    image_url = ""
    for im in soup.select('img[src]'):
        src = (im.get("src") or "").strip()
        if src.startswith("http") and "WATERMARK" in src:
            image_url = src; break
    if not image_url:
        im = soup.select_one('img[src]')
        if im:
            s = (im.get("src") or "").strip()
            if s.startswith("http"):
                image_url = s

    # --------- normalize: gear / color / fuel (รองรับหลายคีย์ + regex fallback) ----------
    def _first_in(d: dict, keys: List[str]) -> str:
        for k in keys:
            if k in d and d[k]:
                return d[k].strip()
        return ""

    gear_keys  = ["เกียร์", "ระบบเกียร์", "ประเภทเกียร์", "Transmission"]
    color_keys = ["สี", "สีภายนอก", "สีตัวถัง", "Exterior Color", "สีรถ"]
    fuel_keys  = ["เชื้อเพลิง", "ประเภทเชื้อเพลิง", "ชนิดเชื้อเพลิง", "ประเภทพลังงาน", "ประเภทเครื่องยนต์", "น้ำมัน"]

    transmission = _first_in(specs, gear_keys)
    color        = _first_in(specs, color_keys)
    fuel_type    = _first_in(specs, fuel_keys)

    blob = soup.get_text(" ", strip=True)

    if not fuel_type:
        m = re.search(r"(เชื้อเพลิง|ประเภทเชื้อเพลิง|ชนิดเชื้อเพลิง|ประเภทพลังงาน|ประเภทเครื่องยนต์|น้ำมัน)\s*[:：]\s*([A-Za-zก-ฮ0-9/ .\-]+)", blob)
        fuel_type = (m.group(2).strip() if m else "") or fuel_type

    if not transmission:
        m = re.search(r"(เกียร์|ระบบเกียร์|ประเภทเกียร์|Transmission)\s*[:：]\s*([A-Za-zก-ฮ0-9/ .\-]+)", blob)
        transmission = (m.group(2).strip() if m else "") or transmission

    if not color:
        m = re.search(r"(สี|สีภายนอก|สีตัวถัง|Exterior Color|สีรถ)\s*[:：]\s*([A-Za-zก-ฮ0-9/ .\-]+)", blob)
        color = (m.group(2).strip() if m else "") or color

    debug_fuel_meta = {
        "value": fuel_type or "",
        "method": "specs/regex" if fuel_type else "not-found"
    }

    # --------- car type ----------
    car_type = specs.get("ประเภท") or specs.get("ประเภทรถ") or ""

    # --------- attrs_json (เก็บให้ template อ่านตรง ๆ) ----------
    attrs = {
        "ผู้ขาย": seller or "",
        "ชื่อรุ่น": title,
        "ราคา(บาท)": price_clean or price_txt or "",
        "เลขไมล์(กม.)": f"{mileage_km:,}" if mileage_km else "",
        "เกียร์": transmission or "",
        "ที่ตั้งรถ": province or "",
        "สเปกย่อย": specs,
        "ยี่ห้อ": brand,
        "รุ่น": model,
        "ประเภท": car_type or "",
        "สี": color or "",
        "น้ำมัน": fuel_type or "",
        "เชื้อเพลิง": fuel_type or "",
        # สำหรับ export แบบ "min fields"
        "ชื่อรถ": title, "ลิงก์": url, "ลิงก์รูปภาพ": image_url or "",
        "ราคา": price_clean or price_txt or "", "เลขไมล์": f"{mileage_km:,}" if mileage_km else "",
        "จังหวัด": province or "",

        # ===== normalized keys =====
        "seller": (seller or "").strip(),
        "location": (province or "").strip(),
        "gear": (transmission or "").strip(),
        "fuel": (fuel_type or "").strip(),
        "color": (color or "").strip(),
        "body_type": (car_type or "").strip(),
    }

    return {
        "source": "roddonjai",
        "source_url": url,
        "title": title,
        "brand": brand or None,
        "model": model or None,
        "year": year,
        "price_thb": price_int,
        "mileage_km": mileage_km,
        "province": province or None,
        "image_url": image_url or None,
        "attrs_json": attrs,
        "debug_fuel": debug_fuel_meta,
    }

# ----------------- DB upsert -----------------
def upsert_car(db, data: Dict) -> bool:
    source_url = data.get("source_url")
    if not source_url:
        return False

    exist = db.execute(
        select(CarCache).where(CarCache.source_url == source_url)
    ).scalar_one_or_none()

    if exist:
        for k in ("title","brand","model","year","price_thb","mileage_km","province","image_url"):
            v = data.get(k)
            if v is not None and v != "":
                setattr(exist, k, v)
        exist.attrs_json = data.get("attrs_json") or exist.attrs_json
        extra = dict(exist.extra or {})
        extra.update(data.get("attrs_json") or {})
        exist.extra = extra
        db.add(exist)
        return False
    else:
        row = CarCache(
            source="roddonjai",
            source_url=source_url,
            title=data.get("title") or "ไม่ระบุชื่อ",
            brand=data.get("brand"),
            model=data.get("model"),
            year=data.get("year"),
            price_thb=data.get("price_thb"),
            mileage_km=data.get("mileage_km"),
            province=data.get("province"),
            url=source_url,
            image_url=data.get("image_url"),
            extra=data.get("attrs_json"),
            attrs_json=data.get("attrs_json"),
        )
        db.add(row)
        return True

# ----------------- print helpers -----------------
MIN_HEADERS = [
    "ชื่อรถ", "ลิงก์", "ลิงก์รูปภาพ", "ราคา", "เลขไมล์", "ผู้ขาย", "จังหวัด",
    "ยี่ห้อ", "รุ่น", "ประเภท", "สี", "เกียร์", "น้ำมัน"
]

def build_min_fields(data: Dict) -> Dict[str, str]:
    ex = data.get("attrs_json") or {}
    specs = (ex.get("สเปกย่อย") or {}) if isinstance(ex, dict) else {}

    title = data.get("title") or ex.get("ชื่อรุ่น") or ex.get("ชื่อรถ") or ""
    url   = data.get("source_url") or data.get("url") or ""
    img   = data.get("image_url") or ex.get("ลิงก์รูปภาพ") or ex.get("รูปภาพ") or ""
    price = data.get("price_thb")
    price_txt = ex.get("ราคา") or ex.get("ราคา(บาท)") or (f"{price:,.0f}" if price is not None else "")

    mileage_km  = data.get("mileage_km")
    mileage_txt = ex.get("เลขไมล์") or ex.get("เลขไมล์(กม.)") or (f"{mileage_km:,}" if mileage_km is not None else "")

    seller   = ex.get("ผู้ขาย") or ""
    province = data.get("province") or ex.get("จังหวัด") or ex.get("ที่ตั้งรถ") or ""
    brand    = data.get("brand") or ex.get("ยี่ห้อ") or ""
    model    = data.get("model") or ex.get("รุ่น") or ""

    def pick(keys: List[str]) -> str:
        for k in keys:
            if isinstance(ex, dict) and ex.get(k): return ex.get(k)
            if isinstance(specs, dict) and specs.get(k): return specs.get(k)
        return ""

    car_type = ex.get("body_type") or pick(["ประเภทรถ", "ประเภท"])
    color    = ex.get("color") or pick(["สี", "สีภายนอก", "สีตัวถัง", "Exterior Color", "สีรถ"])
    gear     = ex.get("gear") or pick(["เกียร์", "ระบบเกียร์", "ประเภทเกียร์", "Transmission"])
    fuel     = ex.get("fuel") or pick(["น้ำมัน", "เชื้อเพลิง", "ประเภทเชื้อเพลิง", "ชนิดเชื้อเพลิง", "ประเภทพลังงาน", "ประเภทเครื่องยนต์"])

    return {
        "ชื่อรถ": title or "—",
        "ลิงก์": url or "—",
        "ลิงก์รูปภาพ": img or "—",
        "ราคา": (f"{price:,.0f}" if isinstance(price, (int, float)) else (price_txt or "—")) or "—",
        "เลขไมล์": mileage_txt or "—",
        "ผู้ขาย": seller or "—",
        "จังหวัด": province or "—",
        "ยี่ห้อ": brand or "—",
        "รุ่น": model or "—",
        "ประเภท": car_type or "—",
        "สี": color or "—",
        "เกียร์": gear or "—",
        "น้ำมัน": fuel or "—",
    }

def print_min_fields(min_row: Dict[str, str]):
    print("\n" + "="*90)
    for k in MIN_HEADERS:
        v = min_row.get(k, "—")
        print(f"{k:>12} : {v}")
    print("="*90)

# ----------------- main -----------------
def main():
    load_env()

    p = argparse.ArgumentParser(description="Scrape RodDonJai แล้ว upsert เข้า car_cache")
    p.add_argument("--q", type=str, default="", help="คำค้น (จะพิมพ์ในช่องค้นหาบนหน้า list)")
    p.add_argument("--min", dest="min_price", type=int, default=0)
    p.add_argument("--max", dest="max_price", type=int, default=999_999_999)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--chromedriver", type=str, default="")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--debug-dump", action="store_true")
    p.add_argument("--debug-fuel", action="store_true", help="พิมพ์เชื้อเพลิงต่อคันเพื่อดีบัก")
    p.add_argument("--debug-print", action="store_true", help="พิมพ์สรุปคอลัมน์ที่ต้องการต่อคัน")

    args = p.parse_args()
    q = (args.q or "").strip()

    driver = None
    created = 0
    try:
        driver = build_driver(args.chromedriver, args.headless)
        driver.get(BASE_URL)
        wait_any(driver, [LIST_INPUT_CSS, "#scrollDivResult, .jss249"])
        time.sleep(0.8)

        # ใส่คำค้นในช่องแล้ว Enter
        if q:
            try:
                inp = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, LIST_INPUT_CSS)))
                inp.clear()
                inp.send_keys(q)
                inp.send_keys(Keys.ENTER)
                time.sleep(1.2)
            except Exception as e:
                # fallback JS
                try:
                    driver.execute_script("""
                        const el = document.querySelector(arguments[0]);
                        if (el) {
                          el.value = arguments[1];
                          el.dispatchEvent(new Event('input',{bubbles:true}));
                          el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
                          return true;
                        }
                        return false;
                    """, LIST_INPUT_CSS, q)
                    time.sleep(1.2)
                except Exception:
                    print("RDJ: search typing error:", e)

        wait_any(driver, ["#scrollDivResult, .jss249, a[href^='/service/car-detail/']"])
        auto_scroll(driver, rounds=12, delay=1.0)

        if args.debug_dump:
            with open("roddonjai_results.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("Saved roddonjai_results.html")

        links = collect_links(driver, limit=args.limit, q=q)
        print(f"RDJ: Found {len(links)} listing links (filtered by keywords)")

        db = SessionLocal()
        try:
            for i, link in enumerate(links, 1):
                try:
                    driver.get(link)
                    wait_any(driver, [".css-ldavcx, .MuiCollapse-wrapperInner, .MuiGrid-item"])
                    time.sleep(0.6)
                    data = parse_detail(driver, link, debug_fuel=args.debug_fuel)

                    # กรองคำค้นซ้ำ (กัน false positive)
                    if q:
                        blob = " ".join([str(data.get("title") or ""), str(data.get("brand") or ""), str(data.get("model") or "")])
                        if not _all_words_in(blob, q):
                            print(f"#{i} skip kw (not match '{q}') -> {link}")
                            continue

                    price = data.get("price_thb")
                    if price is not None and (price < args.min_price or price > args.max_price):
                        print(f"#{i} skip (price {price} not in {args.min_price}-{args.max_price})")
                        continue

                    if args.debug_fuel:
                        dbg = data.get("debug_fuel", {}) or {}
                        print(f"[FUEL] #{i} -> {dbg.get('value') or 'N/A'} | method={dbg.get('method') or '-'} | url={link}")

                    if upsert_car(db, data):
                        created += 1
                    db.commit()

                    # พิมพ์ summary เฉพาะคอลัมน์ที่ต้องการ (ไม่มี 'รุ่นย่อย')
                    if args.debug_print:
                        min_row = build_min_fields(data)
                        print_min_fields(min_row)

                    print(f"#{i} ok -> {data.get('brand') or ''} {data.get('model') or ''} price={price}")
                except Exception as e:
                    print(f"#{i} error: {e}")
                    try:
                        db.commit()
                    except Exception:
                        db.rollback()
            print(f"Upserted {created} rows to car_cache (source=roddonjai)")
        finally:
            db.close()
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

if __name__ == "__main__":
    main()
