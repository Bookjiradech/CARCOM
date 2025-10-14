# -*- coding: utf-8 -*-
"""
Scrape One2car -> CarCache (เก็บรูปเดียวแบบสะอาดลง DB)
ตัวอย่าง:
  python scripts/scrape_one2car.py --q "Honda City" --min 0 --max 700000 --limit 20 --chromedriver "C:\\ScrapingCar\\chromedriver.exe" --headless --debug-dump
"""

import os
import re
import sys
import time
import json
import html
import argparse
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit, quote, unquote

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

BASE_URL = "https://www.one2car.com/"
SEARCH_URL = "https://www.one2car.com/รถมือสอง-สำหรับ-ขาย"


# ------------------------------ utils ---------------------------------
def to_int(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    s = str(s)
    s = re.sub(r"[^\d]", "", s)
    return int(s) if s else None


def only_digits_text(el_text: str) -> Optional[int]:
    if not el_text:
        return None
    m = re.search(r"([\d,]+)", el_text.replace("\u202f", " ").replace("\xa0", " "))
    return to_int(m.group(1)) if m else None


def build_driver(chromedriver_path: Optional[str], headless: bool):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    # ลด noise / ปัญหา GPU/SSL/Logging
    options.add_argument("--window-size=1440,900")
    options.add_argument("--disable-notifications")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
    options.page_load_strategy = "eager"

    if chromedriver_path:
        service = Service(chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)

    driver.set_page_load_timeout(60)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )
    except Exception:
        pass
    return driver


def dismiss_banners(driver):
    # ปิดคุ้กกี้/โมดัล
    candidates = [
        (By.CSS_SELECTOR, "#onetrust-accept-btn-handler"),
        (By.XPATH, "//button[contains(., 'ยอมรับ') or contains(., 'ตกลง') or contains(., 'Accept')]"),
        (By.CSS_SELECTOR, "button[aria-label='Close']"),
        (By.CSS_SELECTOR, ".js-close, .js-modal-close, .modal .close"),
    ]
    for by, sel in candidates:
        try:
            for b in driver.find_elements(by, sel)[:2]:
                b.click()
                time.sleep(0.2)
        except Exception:
            pass


def wait_dom(driver, by, selector, timeout=12):
    return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, selector)))


def scroll_into_view(driver, el):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    except Exception:
        pass


# ------------------------------ search flow ---------------------------------
def perform_search(driver, q: str):
    """
    เปิดหน้าโฮม one2car -> กรอกคีย์เวิร์ดช่อง 'คุณกำลังมองหารถรุ่นไหนอยู่?' -> คลิกปุ่ม 'ค้นหา'
    รองรับอินพุตแบบ Selectize (element ที่เห็นเป็น input ใน .selectize-control)
    """
    driver.get(BASE_URL)
    time.sleep(1.2)
    dismiss_banners(driver)

    # รอ form หลัก
    form = WebDriverWait(driver, 12).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "form.classified-form.js-classified-form"))
    )

    # 1) วิธีหลัก: พิมพ์ลง "input ที่มองเห็น" ของ selectize
    typed = False
    try:
        visible_input = form.find_element(
            By.CSS_SELECTOR,
            ".selectize-control.selectize-keyword input[type='text']"
        )
        visible_input.click()
        visible_input.clear()
        visible_input.send_keys(q)
        time.sleep(0.3)
        visible_input.send_keys(Keys.ENTER)  # trigger on enter
        typed = True
    except Exception:
        pass

    # 2) Fallback: ใช้ JS set ค่าไปที่ selectize โดยตรง
    if not typed:
        try:
            driver.execute_script("""
                (function(q){
                    var form = document.querySelector('form.classified-form.js-classified-form');
                    if(!form) return;
                    var real = form.querySelector('input[name="keyword"]');
                    var vis = form.querySelector('.selectize-control.selectize-keyword input[type="text"]');
                    if (vis) {
                        vis.value = q;
                        vis.dispatchEvent(new Event('input', {bubbles:true}));
                        vis.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
                    }
                    if (real) {
                        real.value = q;
                        real.dispatchEvent(new Event('change', {bubbles:true}));
                    }
                })(arguments[0]);
            """, q)
            time.sleep(0.5)
        except Exception:
            pass

    # คลิกปุ่ม "ค้นหา"
    try:
        submit_btn = form.find_element(By.CSS_SELECTOR, "button.btn.btn--primary[type='submit']")
        submit_btn.click()
    except Exception:
        try:
            driver.execute_script("document.querySelector('form.classified-form.js-classified-form').submit();")
        except Exception:
            pass

    # รอให้หน้า results โหลดการ์ดประกาศ
    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "article.listing.c-listing, article.c-listing"))
        )
    except Exception:
        # ไหลลงเพื่อกระตุ้น lazy load
        for _ in range(8):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.7)
            if driver.find_elements(By.CSS_SELECTOR, "article.listing.c-listing, article.c-listing"):
                break


def collect_listing_links(driver, limit: int) -> List[str]:
    links: List[str] = []
    cards = driver.find_elements(By.CSS_SELECTOR, "article.listing.c-listing, article.c-listing")
    for card in cards:
        try:
            a = card.find_element(By.CSS_SELECTOR, "a.c-stretched-link")
            href = a.get_attribute("href")
            if href and href.startswith("http"):
                links.append(href)
        except Exception:
            continue

    if len(links) < limit:
        for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/for-sale/']"):
            try:
                href = a.get_attribute("href")
                if href and href.startswith("http"):
                    links.append(href)
            except Exception:
                pass

    # unique ลำดับเดิม
    seen, uniq = set(), []
    for u in links:
        if u not in seen:
            uniq.append(u); seen.add(u)
        if len(uniq) >= limit:
            break
    return uniq


# ------------------------------ section helpers ---------------------------------
def ensure_specs_tab_open(driver):
    """
    คลิกแท็บ 'ข้อมูลจำเพาะ' เพื่อให้ DOM ของสเปก (เกียร์/เชื้อเพลิง ฯลฯ) ปรากฏ
    """
    try:
        tab = driver.find_element(By.CSS_SELECTOR, "a.c-tab__item[href='#tab-specifications'], a.c-tab__item[data-toggle='tab'][href='#tab-specifications']")
        scroll_into_view(driver, tab)
        tab.click()
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#tab-specifications .u-text-bold, #tab-specifications .u-border-bottom"))
        )
        time.sleep(0.2)
    except Exception:
        pass


# ------------------------------ image helpers ---------------------------------
def clean_image_url(u: str, drop_query: bool = False) -> str:
    """ล้าง URL: unescape, ตัด whitespace/zero-width, รวม %XX, encode path ให้ถูกต้อง"""
    if not u:
        return ""
    u = html.unescape(u).replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    u = re.sub(r"\s+", "", u)
    u = re.sub(r"%\s*([0-9A-Fa-f]{2})", r"%\1", u)
    sp = urlsplit(u)
    safe_path = quote(unquote(sp.path), safe="/%._-")
    query = "" if drop_query else sp.query
    return urlunsplit((sp.scheme, sp.netloc, safe_path, query, sp.fragment))


def to_jpg_fallback(u: str) -> str:
    """แปลงท้าย .jpg.webp / .jpeg.webp / .png.webp -> .jpg/.jpeg/.png"""
    if not u:
        return ""
    sp = urlsplit(u)
    path = re.sub(r"\.(jpe?g|png)\.webp$", r".\1", sp.path, flags=re.I)
    return urlunsplit((sp.scheme, sp.netloc, path, sp.query, sp.fragment))


def pick_one_image_pair(driver) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    คืน (raw_url, clean_webp, clean_jpg) สำหรับ 'หนึ่งรูป'
    - เลือกจาก data-images ก่อน, รองลงมาคือ <img>/<source> icarcdn
    - clean แล้วทำ jpg fallback
    """
    # 1) data-images ใน #details-gallery
    try:
        sec = driver.find_element(By.CSS_SELECTOR, "section#details-gallery[data-images]")
        raw_json = sec.get_attribute("data-images") or ""
        if raw_json:
            data = json.loads(raw_json)
            if isinstance(data, dict):
                for _, v in sorted(data.items(), key=lambda kv: int(str(kv[0]))):
                    if isinstance(v, str) and v.strip():
                        raw = v.strip()
                        webp = clean_image_url(raw)
                        jpg = to_jpg_fallback(webp)
                        return raw, webp, jpg
    except Exception:
        pass

    # 2) icarcdn จาก <img>/<source>
    try:
        nodes = driver.find_elements(By.CSS_SELECTOR,
            "img[src*='icarcdn.com'], img[data-src*='icarcdn.com'], picture source[srcset*='icarcdn.com']")
        for n in nodes:
            for attr in ("src", "data-src", "srcset"):
                v = (n.get_attribute(attr) or "").strip()
                if not v:
                    continue
                if attr == "srcset":
                    v = v.split(",")[0].split()[0]
                if v.startswith("http"):
                    raw = v
                    webp = clean_image_url(raw)
                    jpg = to_jpg_fallback(webp)
                    return raw, webp, jpg
    except Exception:
        pass

    # 3) รูปอื่น ๆ
    try:
        nodes = driver.find_elements(By.CSS_SELECTOR, "img[src], img[data-src], picture source[srcset]")
        for n in nodes:
            for attr in ("src", "data-src", "srcset"):
                v = (n.get_attribute(attr) or "").strip()
                if not v:
                    continue
                if attr == "srcset":
                    v = v.split(",")[0].split()[0]
                if v.startswith("http"):
                    raw = v
                    webp = clean_image_url(raw)
                    jpg = to_jpg_fallback(webp)
                    return raw, webp, jpg
    except Exception:
        pass

    return None, None, None


# ------------------------------ price parsers ---------------------------------
def parse_special_price_in_gallery(driver) -> Optional[int]:
    try:
        gal = driver.find_element(By.CSS_SELECTOR, "#details-gallery")
    except Exception:
        return None

    try:
        cand = gal.find_elements(By.XPATH, ".//div[contains(@class,'listing__item-price')]//*[contains(normalize-space(.),'บาท')]")
        for el in cand:
            txt = (el.text or "").strip()
            if not txt or "ราคาเฉลี่ย" in txt or "เฉลี่ย" in txt:
                continue
            n = only_digits_text(txt)
            if n:
                return n
    except Exception:
        pass

    try:
        all_txt = gal.find_elements(By.XPATH, ".//*[contains(normalize-space(.),'บาท')]")
        for el in all_txt[:12]:
            t = (el.text or "").strip()
            if not t or "ราคาเฉลี่ย" in t or "เฉลี่ย" in t:
                continue
            n = only_digits_text(t)
            if n:
                return n
    except Exception:
        pass

    return None


def parse_price(driver) -> Optional[int]:
    sp = parse_special_price_in_gallery(driver)
    if sp:
        return sp

    texts = []
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, ".c-card__price-value, .c-card__price .u-text-bold, .listing__price, [data-testing-id='price']"):
            txt = el.text.strip()
            if txt:
                texts.append(txt)
    except Exception:
        pass

    if not texts:
        try:
            candidates = driver.find_elements(By.XPATH, "//*[contains(text(),'บาท') or contains(text(),'฿')]")
            for el in candidates[:10]:
                t = el.text.strip()
                if t and ("ราคาเฉลี่ย" not in t) and ("เฉลี่ย" not in t):
                    texts.append(t)
        except Exception:
            pass

    if not texts:
        try:
            for s in driver.find_elements(By.CSS_SELECTOR, 'script[type="application/ld+json"]'):
                try:
                    data = json.loads(s.get_attribute("innerText") or "{}")
                except Exception:
                    continue
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    offers = item.get("offers")
                    if isinstance(offers, dict):
                        p = offers.get("price") or offers.get("lowPrice") or offers.get("highPrice")
                        if p:
                            return to_int(p)
                    elif isinstance(offers, list) and offers:
                        p = offers[0].get("price") if isinstance(offers[0], dict) else None
                        if p:
                            return to_int(p)
        except Exception:
            pass

    for t in texts:
        n = only_digits_text(t)
        if n is not None:
            return n
    return None


# ------------------------------ detail parsers ---------------------------------
def parse_key_details(driver) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        cards = driver.find_elements(By.CSS_SELECTOR, ".c-key-details__item .c-card__body")
        for c in cards:
            try:
                label = c.find_element(By.CSS_SELECTOR, "span.u-color-muted").text.strip()
                val = c.find_element(By.CSS_SELECTOR, "span.u-text-bold").text.strip()
                if label and val:
                    out[label] = val
            except Exception:
                continue
    except Exception:
        pass
    return out


def parse_seller_and_location(driver) -> Tuple[Optional[str], Optional[str]]:
    seller = None
    location = None

    try:
        sels = [
            "div[class*='seller'] h2",
            "div.c-seller h2",
            "h2.u-text-6",
            ".seller__name, .c-seller__name, .u-text-bold.seller-name",
        ]
        for sel in sels:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                txt = el.text.strip()
                if txt and len(txt) >= 2:
                    seller = txt
                    break
            if seller:
                break
    except Exception:
        pass

    try:
        loc_candidates = [
            "div[class*='location']",
            "div.c-card__location",
            ".seller__address",
            ".c-seller__address",
            ".u-text-truncate.c-card__label",
            "span.c-chip"
        ]
        for sel in loc_candidates:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                txt = el.text.strip()
                if txt and any(k in txt for k in ["กรุงเทพ", "นคร", "บุรี", "จังหวัด", "ปริมณฑล", "เชียง", "ภูเก็ต", "สมุทร", "ราชบุรี"]):
                    location = txt.replace("•", "").strip(" ,")
                    break
            if location:
                break
    except Exception:
        pass

    # JSON-LD สำรอง
    if not location:
        try:
            for s in driver.find_elements(By.CSS_SELECTOR, 'script[type="application/ld+json"]'):
                try:
                    data = json.loads(s.get_attribute("innerText") or "{}")
                except Exception:
                    continue
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict): 
                        continue
                    addr = item.get("address")
                    if isinstance(addr, dict):
                        loc = addr.get("addressLocality") or addr.get("addressRegion")
                        if loc:
                            location = str(loc)
                            break
                if location:
                    break
        except Exception:
            pass

    return seller, location


def parse_brand_model_from_title(title: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not title:
        return None, None
    parts = title.split()
    if len(parts) >= 2:
        return (parts[1].capitalize() if parts[0].isdigit() else parts[0].capitalize(),
                parts[2] if parts[0].isdigit() and len(parts) >= 3 else (parts[1] if len(parts) >= 2 else None))
    return None, None


def parse_detail(driver) -> Dict:
    data: Dict = {}

    # Title
    try:
        h1 = driver.find_element(By.CSS_SELECTOR, "h1.listing__title, h1")
        title = h1.text.strip()
    except Exception:
        title = ""
    data["ชื่อประกาศ"] = title
    data["ชื่อรถ"] = title  # ให้ตรงกับชุดฟิลด์แบบย่อ

    # (ให้แท็บ 'ข้อมูลจำเพาะ' โชว์ก่อนอ่าน key details)
    ensure_specs_tab_open(driver)

    # ราคา
    price_thb = parse_price(driver)
    if price_thb is not None:
        data["ราคา"] = f"{price_thb}"

    # key details
    kv = parse_key_details(driver)
    if "ปีที่ผลิต" in kv:
        data["ปีรถ"] = kv["ปีที่ผลิต"]; data["ปี"] = kv["ปีที่ผลิต"]
    if "เลขไมล์ (กม.)" in kv:
        data["เลขไมล์"] = kv["เลขไมล์ (กม.)"]
    if "ระบบเกียร์" in kv:
        data["ระบบเกียร์"] = kv["ระบบเกียร์"]
        data["เกียร์"] = kv["ระบบเกียร์"]
    if "สี" in kv:
        data["สี"] = kv["สี"]
    if "ประเภทเชื้อเพลิง" in kv:
        # *** สำคัญ: normalize ให้ครบทุกคีย์ที่ระบบใช้อยู่ ***
        fuel = kv["ประเภทเชื้อเพลิง"]
        data["ประเภทเชื้อเพลิง"] = fuel
        data["เชื้อเพลิง"] = fuel
        data["น้ำมัน"] = fuel
        data["fuel_type_normalized"] = str(fuel).strip().lower()

    # รูปเดียว (clean) + เก็บ raw/webp/jpg ไว้ debug
    img_raw, img_webp, img_jpg = pick_one_image_pair(driver)
    if img_raw:
        data["ลิงก์รูป_raw"] = img_raw
    if img_webp:
        data["ลิงก์รูป_webp"] = img_webp
    if img_jpg:
        data["ลิงก์รูป_jpg"] = img_jpg

    final_img = img_jpg or img_webp
    if final_img:
        data["ลิงก์รูป"] = final_img
        data["รูปภาพ"] = final_img

    # ผู้ขาย + ที่ตั้ง
    seller, location = parse_seller_and_location(driver)
    if seller:
        data["ผู้ขาย"] = seller
    if location:
        data["จังหวัด"] = location

    # แบรนด์/รุ่นจาก title (เดา)
    brand, model = parse_brand_model_from_title(title)
    if brand:
        data["ยี่ห้อ"] = brand
    if model:
        data["รุ่น"] = model

    return data


# ------------------------------ DB upsert ---------------------------------
def upsert_car(db, data: Dict) -> bool:
    source_url = data.get("ลิงก์") or data.get("ลิงค์รถ") or data.get("url") or data.get("link")
    if not source_url:
        return False

    title = data.get("ชื่อประกาศ") or data.get("ชื่อรถ") or data.get("title")
    price_thb = to_int(data.get("ราคา") or data.get("price"))
    brand = data.get("ยี่ห้อ") or data.get("brand")
    model = data.get("รุ่น") or data.get("model")
    year = to_int(data.get("ปีรถ") or data.get("ปี") or data.get("year"))
    mileage_km = to_int(data.get("เลขไมล์") or data.get("mileage"))
    province = data.get("จังหวัด") or data.get("location")
    image_url = data.get("ลิงก์รูป") or data.get("รูปภาพ") or data.get("image")

    # extra fields (debug/แสดงผล) — สำเนาคีย์สำคัญลง extra เพื่อให้ UI อ่านง่าย
    extra = data.get("extra") or {}
    for k in (
        "ผู้ขาย", "สี", "เกียร์", "ระบบเกียร์",
        "น้ำมัน", "เชื้อเพลิง", "ประเภทเชื้อเพลิง",  # << เพิ่มประเภทเชื้อเพลิง
        "ลิงก์รูป_raw", "ลิงก์รูป_webp", "ลิงก์รูป_jpg"
    ):
        if data.get(k):
            extra[k] = data[k]

    exist = db.execute(select(CarCache).where(CarCache.source_url == source_url)).scalar_one_or_none()

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
            exist.province = province
        if image_url:
            exist.image_url = image_url

        # เก็บ attrs + extra ให้ครบ
        attrs = dict(exist.attrs_json or {})
        attrs.update(data)
        attrs["extra"] = {**(attrs.get("extra") or {}), **extra}

        exist.attrs_json = attrs
        exist.extra = {**(exist.extra or {}), **extra}
        db.add(exist)
        return False
    else:
        row = CarCache(
            source="one2car",
            source_id=None,
            source_url=source_url,
            title=title or (f"{brand or ''} {model or ''}".strip() or "ไม่ระบุชื่อ"),
            price_thb=price_thb,
            brand=brand,
            model=model,
            year=year,
            mileage_km=mileage_km,
            province=province,
            image_url=image_url,
            attrs_json=data,
            extra=extra,
        )
        db.add(row)
        return True


# ------------------------------ main ---------------------------------
def main():
    parser = argparse.ArgumentParser(description="Scrape One2car to car_cache")
    parser.add_argument("--q", type=str, default="", help="คำค้นหา (เช่น Honda City)")
    parser.add_argument("--min", dest="min_price", type=int, default=0, help="ราคาต่ำสุด")
    parser.add_argument("--max", dest="max_price", type=int, default=999999999, help="ราคาสูงสุด")
    parser.add_argument("--limit", type=int, default=20, help="จำนวนรายการสูงสุด")
    parser.add_argument("--chromedriver", type=str, default="", help="พาธของ chromedriver.exe")
    parser.add_argument("--headless", action="store_true", help="รันแบบ headless")
    parser.add_argument("--debug-dump", action="store_true", help="บันทึก HTML หน้าผลลัพธ์/รายละเอียดไว้ดู (one2car_*.html)")
    args = parser.parse_args()

    driver = None
    created_count = 0

    try:
        driver = build_driver(args.chromedriver, args.headless)

        q = (args.q or "").strip()
        if q:
            perform_search(driver, q)
        else:
            driver.get(SEARCH_URL)
            time.sleep(1.2)
            dismiss_banners(driver)

        if args.debug_dump:
            with open("one2car_results.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)

        links = collect_listing_links(driver, limit=args.limit)
        print(f"Found {len(links)} listing links")

        db = SessionLocal()
        try:
            for idx, link in enumerate(links, start=1):
                try:
                    driver.get(link)
                    wait_dom(driver, By.TAG_NAME, "body", timeout=15)
                    dismiss_banners(driver)

                    if args.debug_dump and idx == 1:
                        with open("one2car_detail.html", "w", encoding="utf-8") as f:
                            f.write(driver.page_source)

                    data = parse_detail(driver)
                    data["ลิงก์"] = link
                    data["ลิงค์รถ"] = link  # alias

                    # filter by price range
                    p = to_int(data.get("ราคา"))
                    if p is not None and (p < args.min_price or p > args.max_price):
                        print(f"[skip price] {p} not in {args.min_price}-{args.max_price} -> {link}")
                        continue

                    if upsert_car(db, data):
                        created_count += 1

                    db.commit()

                    img_dbg = data.get("ลิงก์รูป") or data.get("ลิงก์รูป_jpg") or data.get("ลิงก์รูป_webp") or "-"
                    print(f"[{idx}/{len(links)}] OK -> {data.get('ชื่อประกาศ','(no title)')} | price={data.get('ราคา')} | img={img_dbg}")

                except Exception as e:
                    print(f"[{idx}] error: {e}")
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    continue

            print(f"Upserted {created_count} rows to car_cache (source=one2car)")
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
