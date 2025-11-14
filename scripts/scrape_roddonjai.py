# -*- coding: utf-8 -*-
"""
Scrape RodDonJai แล้ว upsert เข้า car_cache

ตัวอย่างรัน:
  python scripts\scrape_roddonjai.py --q "Honda City" --min 0 --max 999999999 --limit 40 --chromedriver "C:\File\CARCOM\backend\chromedriver.exe" --headless --debug-fuel
"""

import os, sys, re, time, argparse
from typing import Optional, Dict, List
from urllib.parse import urljoin, quote_plus

from dotenv import load_dotenv
from bs4 import BeautifulSoup

# ให้ import app.* ได้
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from app.db import SessionLocal
from app.models import CarCache

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys  # ยังเผื่อใช้ได้ แม้จะไม่พิมพ์แล้ว
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


BASE_URL = "https://www.roddonjai.com/"


# ----------------- utils -----------------
def load_env():
    load_dotenv()


def to_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    s = re.sub(r"[^\d]", "", str(s))
    return int(s) if s else None


def clean_money(t: str) -> str:
    """
    แปลงข้อความราคามาเป็นตัวเลขล้วน เช่น:
      '528,000.-' -> '528,000'
      '฿ 528,000 บาท' -> '528,000'
    ถ้าหา pattern ตัวเลขไม่เจอ -> ''
    """
    t = (t or "").strip()
    if not t:
        return ""
    m = re.search(r"(\d[\d,\.]*)", t)
    if not m:
        return ""
    val = m.group(1)
    # เคส "528,000." → ตัดจุดท้ายทิ้ง
    if val.endswith("."):
        val = val[:-1]
    return val


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


def auto_scroll_until_stable(
    driver, get_count_fn, cooldown=1.0, stable_ticks=3, max_rounds=120
):
    """เลื่อนลงเรื่อย ๆ จนจำนวนการ์ดไม่เพิ่มติดต่อกัน stable_ticks ครั้ง"""
    last = -1
    same = 0
    rounds = 0
    while rounds < max_rounds:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(cooldown)
        cnt = get_count_fn()
        rounds += 1
        if cnt == last:
            same += 1
        else:
            same = 0
        last = cnt
        if same >= stable_ticks:
            break
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.2)


def is_sold_in_anchor(a_tag) -> bool:
    """เช็คว่าการ์ดรถคันนี้ขายแล้วหรือยัง"""
    if a_tag is None:
        return False
    # ป้าย "ขายแล้ว" แบบ class เฉพาะ
    if a_tag.select_one("p.MuiTypography-root.css-1m41lnq"):
        return True
    return "ขายแล้ว" in a_tag.get_text(" ", strip=True)


def collect_links(driver, limit: int, exclude_sold: bool = True) -> List[str]:
    """เก็บลิงก์รถจากหน้า list ของ RodDonJai"""
    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")

    links, seen = [], set()
    kept, sold = 0, 0

    for a in soup.select('a[href^="/service/car-detail/"]'):
        href = (a.get("href") or "").strip()
        href = re.sub(r"[#?].*$", "", href).rstrip("/")
        if not href:
            continue
        full = urljoin(driver.current_url, href)
        if full in seen:
            continue

        flag_sold = is_sold_in_anchor(a)
        if exclude_sold and flag_sold:
            sold += 1
            continue

        links.append(full)
        seen.add(full)
        kept += 1

        if len(links) >= limit:
            break

    # 🔧 เปลี่ยนจากอีโมจิ 🔎 เป็นข้อความธรรมดา เพื่อเลี่ยง UnicodeEncodeError บน Windows cp874
    print(f"[RODDONJAI] collected total={kept+sold} kept={kept} sold_skipped={sold}")
    return links[:limit]


def extract_year(text: str) -> Optional[int]:
    m = re.search(r"(\d{4})", text or "")
    return int(m.group(1)) if m else None


# ----------------- parse page -----------------
def parse_detail(driver, url: str) -> Dict:
    """ดึงข้อมูลจากหน้า detail ของ RodDonJai แล้ว map เป็นโครงเดียวกับ carsome"""

    soup = BeautifulSoup(driver.page_source, "html.parser")

    def sel_text(selector, default=""):
        el = soup.select_one(selector)
        return (el.get_text(strip=True) if el else default) or default

    # ------------- ชื่อรถ -------------
    title = sel_text(".css-ldavcx p") or sel_text("h1,h2,.jss420") or "ไม่พบชื่อรุ่น"

    # ------------- ราคา -------------
    raw_price = ""

    # 1) class แบบใหม่
    if not raw_price:
        raw_price = sel_text("p.MuiTypography-root.MuiTypography-body1.css-13bl6la")
    # 2) class แบบเดิม
    if not raw_price:
        raw_price = sel_text("p.MuiTypography-subtitle1.jss275")
    # 3) fallback: p ไหนก็ได้ที่เหมือนราคา
    if not raw_price:
        for p in soup.select("p"):
            t = p.get_text(strip=True)
            if re.search(r"\d{2,3}[.,]\d{3}", t):
                raw_price = t
                break

    price_clean = clean_money(raw_price) if raw_price else ""
    price_int = to_int(price_clean)

    # ------------- เลขไมล์ (หัวกล่องสรุป) -------------
    mileage_summary = sel_text(".css-j7qwjs p.MuiTypography-body1")
    mileage_num_str = re.sub(r"[^\d,]", "", mileage_summary) if mileage_summary else ""
    mileage_km = to_int(mileage_num_str) if mileage_num_str else None

    # ------------- ผู้ขาย / จังหวัด -------------
    seller = sel_text("p.MuiTypography-root.css-12zbq1l") or None
    province = sel_text("p.css-1ijcpbd") or None

    # ------------- ตารางสเปก -------------
    specs: Dict[str, str] = {}
    for row in soup.select(
        ".MuiCollapse-wrapperInner .MuiGrid-item .d-flex.justify-content-between.mb-1"
    ):
        k_el = row.select_one("p.w-50:nth-of-type(1)")
        v_el = row.select_one("p.w-50:nth-of-type(2)")
        k = k_el.get_text(strip=True) if k_el else ""
        v = v_el.get_text(strip=True) if v_el else ""
        if k and v:
            specs[k] = v

    # ถ้าในตารางไม่มีเลขไมล์ ให้ใช้จาก summary
    if mileage_km is not None:
        specs.setdefault("เลขไมล์", f"{mileage_km:,} กม.")
    else:
        specs.setdefault("เลขไมล์", "—")

    # ------------- รูปภาพ (เลือก WATERMARK ก่อน) -------------
    image_url = None
    for im in soup.select("img[src]"):
        src = (im.get("src") or "").strip()
        if src.startswith("http") and "WATERMARK" in src:
            image_url = src
            break

    # ------------- แยก brand / model -------------
    brand = specs.get("ยี่ห้อ") or ""
    model = specs.get("รุ่น") or ""

    if not brand or not model:
        m = re.match(r"([A-Za-zก-ฮ]+)\s+(.+)", title)
        if m:
            if not brand:
                brand = m.group(1)
            if not model:
                model = m.group(2)

    brand = brand or None
    model = model or None

    # ------------- ปีรถ -------------
    year = None
    for key in ["ปี", "ปีผลิต", "ปีจดทะเบียน", "ปีที่จดทะเบียน"]:
        if key in specs:
            year = extract_year(specs.get(key) or "")
            if year:
                break
    if not year:
        year = extract_year(title)

    # ------------- เชื้อเพลิง / ประเภทเครื่องยนต์ -------------
    fuel_type = (specs.get("ประเภทเครื่องยนต์") or "").strip()
    fuel_key = "ประเภทเครื่องยนต์" if fuel_type else ""
    fuel_method = "specs" if fuel_type else "not-found"

    # ------------- attrs_json -------------
    attrs: Dict[str, object] = {
        "ผู้ขาย": seller or "RODDONJAI",
        "ชื่อรุ่น": title,
        "ราคา(บาท)": price_clean or raw_price or "",
        "เลขไมล์(กม.)": f"{mileage_km:,}" if mileage_km is not None else "",
        "จังหวัด": province or "",
        "สเปกย่อย": specs,
    }

    if fuel_type:
        # ใส่ key เหมือน carsome ให้ template อ่านง่าย
        attrs["ประเภทเชื้อเพลิง"] = fuel_type
        attrs["เชื้อเพลิง"] = fuel_type
        attrs["fuel_type_normalized"] = fuel_type.lower()
        if isinstance(attrs.get("สเปกย่อย"), dict):
            attrs["สเปกย่อย"].setdefault("เชื้อเพลิง", fuel_type)

    debug_fuel = {"value": fuel_type, "key": fuel_key, "method": fuel_method}

    return {
        "source": "roddonjai",
        "source_url": url,
        "title": title,
        "brand": brand,
        "model": model,
        "year": year,
        "price_thb": price_int,
        "mileage_km": mileage_km,
        "province": province,
        "image_url": image_url,
        "attrs_json": attrs,
        "debug_fuel": debug_fuel,
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
        # update ฟิลด์หลัก
        for k in (
            "title",
            "brand",
            "model",
            "year",
            "price_thb",
            "mileage_km",
            "province",
            "image_url",
        ):
            v = data.get(k)
            if v is not None and v != "":
                setattr(exist, k, v)

        # attrs_json / extra
        new_attrs = data.get("attrs_json") or {}
        if new_attrs:
            exist.attrs_json = new_attrs
            extra = dict(exist.extra or {})
            extra.update(new_attrs)
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


# ----------------- main -----------------
def main():
    load_env()

    p = argparse.ArgumentParser(description="Scrape RodDonJai แล้ว upsert เข้า car_cache")
    p.add_argument("--q", type=str, default="", help="คำค้น (จะเอาไปใช้ใน keyword search)")
    p.add_argument("--min", dest="min_price", type=int, default=0)
    p.add_argument("--max", dest="max_price", type=int, default=999_999_999)
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--chromedriver", type=str, default="")
    p.add_argument("--headless", action="store_true")
    p.add_argument(
        "--include-sold",
        action="store_true",
        help="ถ้าใส่ flag นี้ จะแถมคันที่ขายแล้วมาด้วย",
    )
    p.add_argument("--debug-dump", action="store_true")
    p.add_argument(
        "--debug-fuel", action="store_true", help="พิมพ์ fuel type ต่อคันเพื่อดีบัก"
    )

    args = p.parse_args()
    raw_q = (args.q or "").strip()   # เก็บคำค้นจาก CLI จริง ๆ
    q = raw_q
    exclude_sold = not args.include_sold

    driver = None
    created = 0

    try:
        driver = build_driver(args.chromedriver, args.headless)

        # ----- แทนการพิมพ์ในช่องค้นหา → ยิงเข้า search URL โดยตรง -----
        if q:
            kw = quote_plus(q)
            search_url = (
                "https://www.roddonjai.com/search"
                "?brandList=&carFuelList=&carInterestList=&carTypeList=&colorCodeList="
                "&downPercent=&downPrice=&gearList=&installment="
                f"&keyword={kw}"
                "&lat=&lng=&locationId=&maxMileage=&maxPrice=20000000"
                "&minMileage=&minPrice=0&modelList=%7B%7D&provinceList="
                "&score=&sellerSubTypeList=&sellingPointList=&subModelList=%7B%7D"
                "&yearFrom=&yearTo="
            )
            print(f"RODDONJAI: go search URL with keyword={q!r}")
            driver.get(search_url)
        else:
            print("RODDONJAI: no keyword, go BASE_URL")
            driver.get(BASE_URL)

        time.sleep(1.0)

        # รอให้ list แสดงผล
        wait_any(driver, ["#scrollDivResult", ".jss249"])
        time.sleep(1.0)

        # auto scroll จนการ์ดนิ่ง
        def count_cards():
            tmp = BeautifulSoup(driver.page_source, "html.parser")
            return len(tmp.select('a[href^="/service/car-detail/"]'))

        auto_scroll_until_stable(driver, count_cards, cooldown=1.0, stable_ticks=3)

        # ดึงลิงก์รถ
        links = collect_links(driver, limit=args.limit, exclude_sold=exclude_sold)
        print(f"Found {len(links)} RodDonJai listing links")

        if args.debug_dump:
            with open("roddonjai_results.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("Saved roddonjai_results.html")

        db = SessionLocal()
        try:
            for i, link in enumerate(links, 1):
                try:
                    driver.get(link)
                    wait_any(
                        driver,
                        [
                            ".css-ldavcx",
                            ".MuiCollapse-wrapperInner",
                            "h1",
                            ".jss420",
                        ],
                        timeout=20,
                    )

                    data = parse_detail(driver, link)

                    # ถ้ามี q → ตรวจซ้ำอีกรอบ ป้องกันเคส search เพี้ยน
                    if raw_q:
                        blob = " ".join(
                            [
                                str(data.get("title") or ""),
                                str(data.get("brand") or ""),
                                str(data.get("model") or ""),
                            ]
                        ).lower()

                        words = [w for w in raw_q.lower().split() if w]

                        if len(words) == 1:
                            # เคสเช่น q = "city"
                            if words[0] not in blob:
                                print(f"#{i} skip kw (not match '{raw_q}') -> {link}")
                                continue
                        else:
                            # เคสเช่น q = "honda city"
                            if not all(w in blob for w in words):
                                print(f"#{i} skip kw (not match '{raw_q}') -> {link}")
                                continue

                    price = data.get("price_thb")
                    if price is not None and (
                        price < args.min_price or price > args.max_price
                    ):
                        print(
                            f"#{i} skip (price {price} not in {args.min_price}-{args.max_price})"
                        )
                        continue

                    if args.debug_fuel:
                        dbg = data.get("debug_fuel", {}) or {}
                        print(
                            f"[FUEL] #{i} -> {dbg.get('value') or 'N/A'} "
                            f"| key={dbg.get('key') or '-'} "
                            f"| method={dbg.get('method') or '-'} "
                            f"| url={link}"
                        )

                    if upsert_car(db, data):
                        created += 1
                    db.commit()

                    print(
                        f"#{i} ok -> {data.get('brand') or ''} {data.get('model') or ''} price={price}"
                    )
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
