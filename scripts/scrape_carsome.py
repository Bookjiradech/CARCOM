# -*- coding: utf-8 -*-
"""
Scrape Carsome แล้ว upsert เข้า car_cache

ตัวอย่าง:
  python scripts\scrape_carsome.py --q "City" --min 0 --max 999999999 --limit 40 --chromedriver "C:\ScrapingCar\chromedriver.exe" --headless --debug-fuel
"""

import os, sys, re, time, argparse
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


BASE_URL = "https://www.carsome.co.th/buy-car"

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

def wait_any(driver, selectors: List[str], timeout=12):
    conds = [EC.presence_of_element_located((By.CSS_SELECTOR, sel)) for sel in selectors]
    WebDriverWait(driver, timeout).until(lambda d: any(c(d) for c in conds))

def auto_scroll(driver, rounds=6, delay=1.0):
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

def is_carsome_car_url(href: str) -> bool:
    if not href:
        return False
    href = re.sub(r'[#?].*$', '', href)
    return "/buy-car/" in href and re.search(r"/[a-z]{3}\d{3,}/?$", href, re.I) is not None

def _all_words_in(text: str, q: str) -> bool:
    q = (q or "").strip().lower()
    words = [w for w in re.split(r"\s+", q) if w]
    if not words:
        return True
    blob = (text or "").lower()
    return all(w in blob for w in words)

def collect_links(driver, limit: int, q: Optional[str] = None) -> List[str]:
    links: List[str] = []
    seen = set()
    try:
        cards = driver.find_elements(By.CSS_SELECTOR, "article.mod-b-card, article.card, article[class*='car-card']")
        for card in cards:
            try:
                a = card.find_element(By.CSS_SELECTOR, "a[href]")
                href = a.get_attribute("href") or ""
                if not href or not href.startswith("http"):
                    continue
                if not is_carsome_car_url(href):
                    continue
                txt = card.text.strip()
                if q and not _all_words_in(txt + " " + href, q):
                    continue
                u = re.sub(r"[#?].*$", "", href).rstrip("/")
                if u not in seen:
                    links.append(u); seen.add(u)
            except Exception:
                continue
    except Exception:
        pass

    if len(links) < limit:
        html = driver.page_source
        hrefs = re.findall(r'href="([^"]+)"', html)
        for h in hrefs:
            u = urljoin(driver.current_url, h)
            u = re.sub(r"[#?].*$", "", u).rstrip("/")
            if not is_carsome_car_url(u):
                continue
            if u not in seen:
                links.append(u); seen.add(u)
            if len(links) >= limit * 2:
                break
    return links[:limit]

def extract_year(text: str) -> Optional[int]:
    m = re.search(r"(\d{4})", text or "")
    return int(m.group(1)) if m else None

# ----------------- parse page -----------------
def parse_detail(driver, url: str) -> Dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(driver.page_source, "html.parser")

    def sel_text(selector, default=""):
        el = soup.select_one(selector)
        return (el.get_text(strip=True) if el else default) or default

    # ===== helper: specs + fuel =====
    def collect_spec_items() -> Dict[str, str]:
        specs: Dict[str, str] = {}
        for row in soup.select(".car-details-content .detail-item, .detail__car-spec .detail-item"):
            key_el = row.select_one(".key")
            val_el = row.select_one(".value")
            k = key_el.get_text(strip=True) if key_el else ""
            v = val_el.get_text(strip=True) if val_el else ""
            if k and v:
                specs[k] = v
        return specs

    def extract_fuel(specs: Dict[str, str]) -> Tuple[str, str, str]:
        fuel_keys = ["ประเภทเชื้อเพลิง", "เชื้อเพลิง", "ประเภทน้ำมัน", "ชนิดเชื้อเพลิง", "ประเภทพลังงาน"]
        for k in fuel_keys:
            if k in specs and specs[k]:
                return specs[k].strip(), k, "specs"
        for row in soup.select(".detail-item"):
            key_el = row.select_one(".key")
            val_el = row.select_one(".value")
            if not key_el or not val_el:
                continue
            k = key_el.get_text(strip=True)
            v = val_el.get_text(strip=True)
            if any(alt in k for alt in fuel_keys):
                return v.strip(), k, "detail-item"
        blob = soup.get_text(" ", strip=True)
        m = re.search(r"(ประเภทเชื้อเพลิง|เชื้อเพลิง|ประเภทน้ำมัน)\s*[:：]\s*([A-Za-zก-ฮ0-9/ \-]+)", blob)
        if m:
            return m.group(2).strip(), m.group(1), "regex"
        return "", "", "not-found"

    # ===== fields =====
    title = (
        sel_text(".vehicle__title-wrapper span")
        or sel_text(".car-info-left .car-info-top")
        or sel_text(".head-mobile__title")
        or sel_text("h1")
        or "ไม่พบชื่อรุ่น"
    )

    price_txt = sel_text(".car-price .price") or sel_text(".detail__price .price") or sel_text(".car__price")
    price_clean = clean_money(price_txt) if price_txt else ""
    price_int = to_int(price_clean)

    mileage_trans = sel_text(".car-mileage") or sel_text(".detail__car-info") or ""
    mil = re.search(r"([\d,]+)\s*กม", mileage_trans)
    mileage_km = to_int(mil.group(1)) if mil else None

    gear_m = re.search(r"\|\s*([A-Za-zก-ฮ]+)", mileage_trans)
    transmission = (gear_m.group(1).strip() if gear_m else "") or sel_text(".transmission") or ""

    location = sel_text(".car-all__location-descs") or sel_text(".detail__location") or ""

    specs = collect_spec_items()
    fuel_type, fuel_key, fuel_method = extract_fuel(specs)

    reg_txt = ""
    for row in soup.select(".car-details-content .detail-item, .detail__car-spec .detail-item"):
        key_el = row.select_one(".key")
        if key_el and ("วันจดทะเบียน" in key_el.get_text(strip=True) or "ปี" == key_el.get_text(strip=True)):
            val_el = row.select_one(".value")
            reg_txt = val_el.get_text(strip=True) if val_el else ""
            break
    year = extract_year(reg_txt) or extract_year(title)

    first_img = ""
    for im in soup.select(".banner__slide img[src], .detail__images img[src]"):
        src = (im.get("src") or "").strip()
        if src.startswith("http"):
            first_img = src
            break

    brand = ""
    model = ""
    m = re.match(r"([A-Za-zก-ฮ]+)\s+([A-Za-z0-9\.\-]+)", title)
    if m:
        brand = m.group(1)
        model = m.group(2)

    attrs = {
        "ผู้ขาย": "CARSOME",
        "ชื่อรุ่น": title,
        "ราคา(บาท)": price_clean or price_txt or "",
        "เลขไมล์(กม.)": f"{mileage_km:,}" if mileage_km else "",
        "เกียร์": transmission,
        "ที่ตั้งรถ": location,
        "สเปกย่อย": specs,
    }
    if fuel_type:
        # *** สำคัญ: ใส่ทั้งสองคีย์ให้เทมเพลตอ่านเจอแน่นอน ***
        attrs["ประเภทเชื้อเพลิง"] = fuel_type
        attrs["เชื้อเพลิง"] = fuel_type
        attrs["fuel_type_normalized"] = fuel_type.lower()
        if isinstance(attrs.get("สเปกย่อย"), dict):
            attrs["สเปกย่อย"].setdefault("เชื้อเพลิง", fuel_type)

    debug_fuel = {"value": fuel_type, "key": fuel_key, "method": fuel_method}

    return {
        "source": "carsome",
        "source_url": url,
        "title": title,
        "brand": brand or None,
        "model": model or None,
        "year": year,
        "price_thb": price_int,
        "mileage_km": mileage_km,
        "province": location or None,
        "image_url": first_img or None,
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
            source="carsome",
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

    p = argparse.ArgumentParser(description="Scrape Carsome แล้ว upsert เข้า car_cache")
    p.add_argument("--q", type=str, default="", help="คำค้น (จะพิมพ์ลงช่องค้นหาบนหน้า list)")
    p.add_argument("--min", dest="min_price", type=int, default=0)
    p.add_argument("--max", dest="max_price", type=int, default=999_999_999)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--chromedriver", type=str, default="")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--debug-dump", action="store_true")
    p.add_argument("--debug-fuel", action="store_true", help="พิมพ์ fuel type ต่อคันเพื่อดีบัก")

    args = p.parse_args()
    q = (args.q or "").strip()

    driver = None
    created = 0
    try:
        driver = build_driver(args.chromedriver, args.headless)
        driver.get(BASE_URL)
        time.sleep(1.0)

        if q:
            try:
                typed = False
                selectors = [
                    (By.CSS_SELECTOR, 'input[type="search"]'),
                    (By.CSS_SELECTOR, 'input[placeholder*="ค้นหา"]'),
                    (By.CSS_SELECTOR, 'form input[type="text"]'),
                ]
                for by, sel in selectors:
                    try:
                        el = WebDriverWait(driver, 6).until(EC.presence_of_element_located((by, sel)))
                        el.clear()
                        el.send_keys(q)
                        el.send_keys(Keys.ENTER)
                        time.sleep(1.2)
                        try:
                            btns = driver.find_elements(By.XPATH, "//button[.='ค้นหา' or contains(., 'ค้นหา')]")
                            if btns:
                                btns[0].click()
                                time.sleep(1.0)
                        except Exception:
                            pass
                        typed = True
                        print(f"CARSOME: typed query via {sel!r}")
                        break
                    except Exception:
                        continue
                if not typed:
                    driver.execute_script("""
                        const ss = ['input[type="search"]','input[placeholder*="ค้นหา"]','form input[type="text"]'];
                        for (const s of ss) {
                          const el = document.querySelector(s);
                          if (el) { el.value = arguments[0];
                            el.dispatchEvent(new Event('input',{bubbles:true}));
                            el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
                            const btn = [...document.querySelectorAll('button')].find(b=>/ค้นหา/.test(b.textContent||''));
                            if (btn) btn.click();
                            return true; }
                        }
                        return false;
                    """, q)
                    time.sleep(1.2)
                    print("CARSOME: typed query via JS fallback")
            except Exception as e:
                print("CARSOME: search typing error:", e)

        wait_any(driver, ["article.mod-b-card", ".detail__popular-car, .detail__car-info"])
        auto_scroll(driver, rounds=8, delay=1.0)

        if args.debug_dump:
            with open("carsome_results.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("Saved carsome_results.html")

        links = collect_links(driver, limit=args.limit, q=q)
        print(f"Found {len(links)} listing links (filtered by keywords)")

        db = SessionLocal()
        try:
            for i, link in enumerate(links, 1):
                try:
                    driver.get(link)
                    wait_any(driver, [".detail__car-info", ".car-price .price", ".vehicle__title-wrapper", "h1"])
                    data = parse_detail(driver, link)

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
                        print(f"[FUEL] #{i} -> {dbg.get('value') or 'N/A'} | key={dbg.get('key') or '-'} | method={dbg.get('method') or '-'} | url={link}")

                    if upsert_car(db, data):
                        created += 1
                    db.commit()

                    print(f"#{i} ok -> {data.get('brand') or ''} {data.get('model') or ''} price={price}")
                except Exception as e:
                    print(f"#{i} error: {e}")
                    try:
                        db.commit()
                    except Exception:
                        db.rollback()
            print(f"Upserted {created} rows to car_cache")
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
