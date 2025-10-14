# -*- coding: utf-8 -*-
"""
ดึงรถจาก Kaidee แล้วอัปเสิร์ตเข้า car_cache
ตัวอย่างรัน:
  python scripts\scrape_kaidee.py --q "City" --min 0 --max 999999999 --limit 40 --chromedriver "C:\ScrapingCar\chromedriver.exe" --headless --debug-fuel
"""

import os, sys, re, time, argparse
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv

# ให้ import app.* ได้เวลาเรียกสคริปต์ตรง ๆ
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

BASE_URL = "https://rod.kaidee.com/c11-auto-car"

def load_env():
    load_dotenv()

def to_int(s: Optional[str]) -> Optional[int]:
    if s is None: return None
    s = re.sub(r"[^\d]", "", str(s))
    if not s: return None
    try: return int(s)
    except Exception: return None

def build_driver(chromedriver_path: Optional[str], headless: bool):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1440,900")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    if chromedriver_path:
        service = Service(chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver

def dismiss_banners(driver):
    candidates = [
        (By.XPATH, "//button[contains(., 'ยอมรับ')]"),
        (By.XPATH, "//button[contains(., 'ตกลง')]"),
        (By.XPATH, "//button[contains(., 'Accept')]"),
        (By.CSS_SELECTOR, "#onetrust-accept-btn-handler"),
        (By.CSS_SELECTOR, "button[aria-label='Close']"),
    ]
    for by, sel in candidates:
        try:
            btns = driver.find_elements(by, sel)
            if btns:
                btns[0].click()
                time.sleep(0.5)
        except Exception:
            pass

def wait_for_results(driver, max_tries=15, sleep_sec=1.0) -> List[str]:
    links: List[str] = []
    for _ in range(max_tries):
        links = find_listing_links(driver)
        if links: break
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(sleep_sec)
    return links

def find_listing_links(driver) -> List[str]:
    links = set()
    try:
        # การ์ดหลัก (คลาสเปลี่ยนบ่อย เลยโฟกัสโครงสร้าง a.block + เงา)
        cards = driver.find_elements(By.CSS_SELECTOR, 'a.block.cursor-pointer.rounded-sm.p-md.shadow-lg')
        for el in cards:
            href = el.get_attribute("href")
            if href: links.add(href)
    except Exception:
        pass
    for css in ['a[href*="product-"]', 'a[href*="/product-"]']:
        try:
            anchors = driver.find_elements(By.CSS_SELECTOR, css)
            for a in anchors:
                href = a.get_attribute("href")
                if href: links.add(href)
        except Exception:
            pass
    return list(links)

# -------- fuel helpers --------
FUEL_KEYS = ["ประเภทเชื้อเพลิง", "เชื้อเพลิง", "ประเภทน้ำมัน", "ชนิดเชื้อเพลิง", "ประเภทพลังงาน"]

def extract_fuel_from_data(d: Dict) -> Tuple[str, str]:
    for k in FUEL_KEYS:
        if k in d and d[k]:
            return d[k], k
    return "", ""

# -------- robust text helper --------
def first_text_by_xpath(driver, xpaths: List[str], timeout: int = 8) -> str:
    for xp in xpaths:
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xp))
            )
            txt = el.text.strip()
            if txt:
                return txt
        except Exception:
            continue
    return ""

def parse_detail_page(driver) -> Dict:
    data: Dict = {}

    # ราคา
    price = None
    try:
        price_el = WebDriverWait(driver, 4).until(
            EC.presence_of_element_located(
                (By.XPATH, "//span[contains(text(),'ราคารวมมูลค่าของแถมแล้ว')]/preceding-sibling::span")
            )
        )
        price = price_el.text.strip()
    except Exception:
        try:
            price_el = driver.find_element(By.XPATH, "//span[contains(text(),'฿') or contains(text(),',')]")
            price = price_el.text.strip()
        except Exception:
            pass
    data["ราคา"] = price or "ไม่พบราคา"

    # ผู้ขาย (ทนชื่อคลาสสุ่ม)
    seller = first_text_by_xpath(driver, [
        "//img[@alt='รูปโปรไฟล์']/ancestor::div[contains(@class,'sc-1t41luv-3')]//span[contains(@class,'sc-3tpgds-0')][1]",
        "//div[contains(@class,'sc-1k125n6-2')]//span[contains(@class,'sc-3tpgds-0')][1]",
        "//span[contains(@class,'sc-3tpgds-0')][1]"
    ])
    data["ผู้ขาย"] = seller if seller else "ไม่พบ"

    # รูป
    img_url = None
    try:
        meta = driver.find_element(By.CSS_SELECTOR, 'meta[property="og:image"]')
        img_url = meta.get_attribute("content")
    except Exception:
        try:
            img = driver.find_element(By.CSS_SELECTOR, "img")
            img_url = img.get_attribute("src")
        except Exception:
            pass
    if img_url:
        data["รูปภาพ"] = img_url

    # Attributes (ปี/ไมล์/เกียร์/เชื้อเพลิง ฯลฯ)
    try:
        items = driver.find_elements(By.CSS_SELECTOR, "ul#has-attributes > li")
        for li in items:
            try:
                label = li.find_element(By.CSS_SELECTOR, "span.sc-3tpgds-0").text.strip()
                value = li.find_element(By.CSS_SELECTOR, "div > span").text.strip()
                if label and value:
                    data[label] = value
            except Exception:
                continue
    except Exception:
        pass

    # ชื่อประกาศ
    try:
        title_el = driver.find_element(By.TAG_NAME, "h1")
        data["ชื่อประกาศ"] = title_el.text.strip()
    except Exception:
        pass

    # ที่อยู่/ตำแหน่ง (ทนชื่อคลาสสุ่ม + fallback)
    location_text = first_text_by_xpath(driver, [
        "//li[.//span[normalize-space()='ตำแหน่ง']]//span[normalize-space()!='ตำแหน่ง'][last()]",
        "//li[.//svg]//span[contains(@class,'sc-mj06cq-1') or contains(@class,'biQatR')][last()]"
    ])
    if location_text:
        data["ที่อยู่"] = location_text
        # ให้มี key มาตรฐานที่ upsert ใช้อ่านเป็น province ด้วย
        data["จังหวัด"] = location_text

    # ----- Fuel normalize -----
    fuel_val, fuel_key = extract_fuel_from_data(data)
    if fuel_val:
        data["ประเภทเชื้อเพลิง"] = fuel_val
        data["เชื้อเพลิง"] = fuel_val               # *** คีย์ที่เทมเพลตอ่าน ***
        data["fuel_type_normalized"] = str(fuel_val).strip().lower()

    return data

def upsert_car(db, data: Dict) -> bool:
    source_url = data.get("ลิงก์") or data.get("url") or data.get("link")
    if not source_url:
        return False

    title = data.get("ชื่อประกาศ") or data.get("title")
    price_thb = to_int(data.get("ราคา") or data.get("price"))
    brand = data.get("ยี่ห้อ") or data.get("brand")
    model = data.get("รุ่น") or data.get("model")
    year = to_int(data.get("ปีรถ") or data.get("year"))
    mileage_km = to_int(data.get("เลขไมล์") or data.get("mileage"))

    # ดึง province/ที่อยู่ ให้ครอบคลุมหลายคีย์
    province = (
        data.get("จังหวัด")
        or data.get("ที่อยู่")
        or data.get("ตำแหน่ง")
        or data.get("location")
    )

    image_url = data.get("รูปภาพ")

    exist = db.execute(
        select(CarCache).where(CarCache.source_url == source_url)
    ).scalar_one_or_none()

    if exist:
        if price_thb is not None:
            exist.price_thb = price_thb
        exist.title = title or exist.title
        exist.brand = brand or exist.brand
        exist.model = model or exist.model
        if year is not None:
            exist.year = year
        if mileage_km is not None:
            exist.mileage_km = mileage_km
        if province:
            exist.province = province          # ← บันทึกที่อยู่/จังหวัด
        if image_url:
            exist.image_url = image_url
        exist.attrs_json = data               # เก็บ raw + ผู้ขาย/ที่อยู่ ไว้หมด
        db.add(exist)
        return False
    else:
        row = CarCache(
            source="kaidee",
            source_url=source_url,
            title=title or (f"{brand or ''} {model or ''}".strip() or "ไม่ระบุชื่อ"),
            price_thb=price_thb,
            brand=brand,
            model=model,
            year=year,
            mileage_km=mileage_km,
            province=province,                # ← แมปเข้าคอลัมน์ province
            image_url=image_url,
            extra=data,                       # เก็บผู้ขาย/ที่อยู่ใน extra ด้วย
        )
        db.add(row)
        return True

def main():
    load_env()

    parser = argparse.ArgumentParser(description="Scrape Kaidee to car_cache")
    parser.add_argument("--q", type=str, default="", help="คำค้นหา (เช่น City)")
    parser.add_argument("--min", dest="min_price", type=int, default=0, help="ราคาต่ำสุด")
    parser.add_argument("--max", dest="max_price", type=int, default=999999999, help="ราคาสูงสุด")
    parser.add_argument("--limit", type=int, default=20, help="จำนวนรายการสูงสุด")
    parser.add_argument("--chromedriver", type=str, default="", help="พาธของ chromedriver.exe")
    parser.add_argument("--headless", action="store_true", help="รันแบบ headless")
    parser.add_argument("--debug-dump", action="store_true", help="บันทึก HTML หน้าแรกไว้ดู (kaidee_results.html)")
    parser.add_argument("--debug-fuel", action="store_true", help="พิมพ์ fuel type ต่อคันเพื่อดีบัก")

    args = parser.parse_args()

    driver = None
    created_count = 0
    try:
        driver = build_driver(args.chromedriver, args.headless)

        driver.get(BASE_URL)
        time.sleep(1)
        dismiss_banners(driver)

        # ----- พิมพ์คำค้นหา (ถ้ามี q) -----
        if args.q:
            typed = False
            try:
                selectors = [
                    (By.XPATH, '//section//form//input'),
                    (By.CSS_SELECTOR, 'section form input[type="text"]'),
                    (By.CSS_SELECTOR, 'input[placeholder*="ค้นหา"]'),
                    (By.CSS_SELECTOR, 'input[type="search"]'),
                ]
                for by, sel in selectors:
                    try:
                        search_input = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((by, sel))
                        )
                        search_input.clear()
                        search_input.send_keys(args.q)
                        search_input.send_keys(Keys.ENTER)
                        time.sleep(1.6)
                        dismiss_banners(driver)
                        typed = True
                        print(f"KAIDEE: typed query via {sel!r}")
                        break
                    except Exception:
                        continue

                if not typed:
                    driver.execute_script("""
                        const candidates = [
                          'section form input[type="text"]',
                          'input[placeholder*="ค้นหา"]',
                          'input[type="search"]',
                          'section form input'
                        ];
                        for (const s of candidates) {
                          const el = document.querySelector(s);
                          if (el) {
                            el.value = arguments[0];
                            el.dispatchEvent(new Event('input', {bubbles:true}));
                            el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
                            return true;
                          }
                        }
                        return false;
                    """, args.q)
                    time.sleep(1.6)
                    dismiss_banners(driver)
                    print("KAIDEE: typed query via JS fallback")
            except Exception as e:
                print("KAIDEE: search typing error:", e)

        if args.debug_dump:
            with open("kaidee_results.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("Saved kaidee_results.html")

        links = wait_for_results(driver, max_tries=15, sleep_sec=1.0)
        links = list(dict.fromkeys(links))[: args.limit]
        print(f"Found {len(links)} listing links")

        db = SessionLocal()
        try:
            for idx, link in enumerate(links, start=1):
                try:
                    driver.get(link)
                    WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                    dismiss_banners(driver)

                    data = parse_detail_page(driver)
                    data["ลิงก์"] = link

                    # DEBUG fuel
                    if args.debug_fuel:
                        fuel_val = data.get("เชื้อเพลิง") or data.get("ประเภทเชื้อเพลิง") or data.get("fuel_type_normalized") or "N/A"
                        print(f"[FUEL] #{idx} -> {fuel_val} | url={link}")

                    p = to_int(data.get("ราคา"))
                    if p is not None and (p < args.min_price or p > args.max_price):
                        print(f"[skip] price {p} not in range {args.min_price}-{args.max_price}")
                        continue

                    if upsert_car(db, data):
                        created_count += 1

                    db.commit()
                    print(f"#{idx} ok -> {data.get('ยี่ห้อ','?')} {data.get('รุ่น','?')} price={data.get('ราคา')} | seller={data.get('ผู้ขาย')} | loc={data.get('จังหวัด') or data.get('ที่อยู่')}")
                except Exception as e:
                    print(f"#{idx} error: {e}")
                    try:
                        db.commit()
                    except Exception:
                        db.rollback()
                    continue

            print(f"Upserted {created_count} rows to car_cache")
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
