# -*- coding: utf-8 -*-
"""
Scrape RodDonJai แล้ว upsert เข้า car_cache

ตัวอย่างรัน:
  python scripts\scrape_roddonjai.py --q "Honda City" --min 0 --max 999999999 --limit 40 --chromedriver "C:\File\CARCOM\backend\chromedriver.exe" --headless --debug-fuel --debug-detail
"""

import os, sys, re, time, argparse
from typing import Optional, Dict, List, Tuple
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
from selenium.common.exceptions import TimeoutException  # สำหรับกัน wait timeout

BASE_URL = "https://www.roddonjai.com/"

# ================== mapping สี / น้ำมัน / เกียร์ / body type / จังหวัด ==================

COLOR_MAP_TH_EN = {
    "ดำ": "Black",
    "ขาว": "White",
    "เทา": "Gray",
    "เงิน": "Silver",
    "แดง": "Red",
    "น้ำเงิน": "Blue",
    "ฟ้า": "Light Blue",
    "เขียว": "Green",
    "ส้ม": "Orange",
    "เหลือง": "Yellow",
    "ชมพู": "Pink",
    "ม่วง": "Purple",
    "น้ำตาล": "Brown",
    "ทอง": "Gold",
    "เบจ": "Beige",
    "ครีม": "Cream",
    "บรอนซ์เงิน": "Silver",
    "บรอนซ์ทอง": "Gold",
    "กากี": "Khaki",
    "กรมท่า": "Navy Blue",
    "โรสโกลด์": "Rose Gold",
    "เนื้อ": "Nude",
    "หลากสี": "Multicolor",
}

FUEL_MAP_TH_EN = {
    "เบนซิน": "Benzine",
    "ดีเซล": "Diesel",
    "ไฮบริด": "Hybrid",
    "ไฟฟ้า": "EV",
    "EV/ไฟฟ้า": "EV",
    "ปลั๊กอินไฮบริด": "PHEV",
    "LPG": "LPG",
    "NGV": "NGV",
    "LPG/NGV": "LPG/NGV",
}

TRANSMISSION_MAP_TH_EN = {
    "เกียร์ธรรมดา": "Manual",
    "ธรรมดา": "Manual",
    "mt": "Manual",
    "เอ็มที": "Manual",
    "เกียร์อัตโนมัติ": "Automatic",
    "อัตโนมัติ": "Automatic",
    "auto": "Automatic",
    "at": "Automatic",
    "เอที": "Automatic",
}

BODY_TYPE_MAP_TH_EN = {
    "รถเก๋ง": "Sedan",
    "เก๋ง": "Sedan",
    "รถเก๋งซีดาน": "Sedan",
    "รถเก๋งขนาดกลาง/ใหญ่": "Large Sedan",
    "รถสปอร์ต": "Sport",
    "ซุปเปอร์สปอร์ต": "Super Sport",
    "รถสปอร์ต/ซุปเปอร์สปอร์ต": "Sport / Super Sport",
    "รถอเนกประสงค์": "MPV/SUV/PPV",
    "อเนกประสงค์": "MPV/SUV/PPV",
    "รถตู้": "Van",
    "ตู้": "Van",
    "รถกระบะ": "Pickup",
    "กระบะ": "Pickup",
}

# จังหวัดไทยทั้งหมด → อังกฤษ
PROVINCE_MAP_TH_EN = {
    "กรุงเทพมหานคร": "Bangkok",
    "กรุงเทพฯ": "Bangkok",
    "กรุงเทพ": "Bangkok",
    "กทม": "Bangkok",
    "กระบี่": "Krabi",
    "กาญจนบุรี": "Kanchanaburi",
    "กาฬสินธุ์": "Kalasin",
    "กำแพงเพชร": "Kamphaeng Phet",
    "ขอนแก่น": "Khon Kaen",
    "จันทบุรี": "Chanthaburi",
    "ฉะเชิงเทรา": "Chachoengsao",
    "ชลบุรี": "Chonburi",
    "ชัยนาท": "Chai Nat",
    "ชัยภูมิ": "Chaiyaphum",
    "ชุมพร": "Chumphon",
    "เชียงราย": "Chiang Rai",
    "เชียงใหม่": "Chiang Mai",
    "ตรัง": "Trang",
    "ตราด": "Trat",
    "ตาก": "Tak",
    "นครนายก": "Nakhon Nayok",
    "นครปฐม": "Nakhon Pathom",
    "นครพนม": "Nakhon Phanom",
    "นครราชสีมา": "Nakhon Ratchasima",
    "โคราช": "Nakhon Ratchasima",
    "นครศรีธรรมราช": "Nakhon Si Thammarat",
    "นครสวรรค์": "Nakhon Sawan",
    "นนทบุรี": "Nonthaburi",
    "นราธิวาส": "Narathiwat",
    "น่าน": "Nan",
    "บึงกาฬ": "Bueng Kan",
    "บุรีรัมย์": "Buri Ram",
    "ปทุมธานี": "Pathum Thani",
    "ประจวบคีรีขันธ์": "Prachuap Khiri Khan",
    "ปราจีนบุรี": "Prachin Buri",
    "ปัตตานี": "Pattani",
    "พระนครศรีอยุธยา": "Phra Nakhon Si Ayutthaya",
    "อยุธยา": "Phra Nakhon Si Ayutthaya",
    "พังงา": "Phang Nga",
    "พัทลุง": "Phatthalung",
    "พิจิตร": "Phichit",
    "พิษณุโลก": "Phitsanulok",
    "เพชรบุรี": "Phetchaburi",
    "เพชรบูรณ์": "Phetchabun",
    "แพร่": "Phrae",
    "ภูเก็ต": "Phuket",
    "มหาสารคาม": "Maha Sarakham",
    "มุกดาหาร": "Mukdahan",
    "แม่ฮ่องสอน": "Mae Hong Son",
    "ยโสธร": "Yasothon",
    "ยะลา": "Yala",
    "ร้อยเอ็ด": "Roi Et",
    "ระนอง": "Ranong",
    "ระยอง": "Rayong",
    "ราชบุรี": "Ratchaburi",
    "ลพบุรี": "Lopburi",
    "ลำปาง": "Lampang",
    "ลำพูน": "Lamphun",
    "เลย": "Loei",
    "ศรีสะเกษ": "Si Sa Ket",
    "สกลนคร": "Sakon Nakhon",
    "สงขลา": "Songkhla",
    "สตูล": "Satun",
    "สมุทรปราการ": "Samut Prakan",
    "สมุทรสงคราม": "Samut Songkhram",
    "สมุทรสาคร": "Samut Sakhon",
    "สระแก้ว": "Sa Kaeo",
    "สระบุรี": "Saraburi",
    "สิงห์บุรี": "Sing Buri",
    "สุโขทัย": "Sukhothai",
    "สุพรรณบุรี": "Suphan Buri",
    "สุราษฎร์ธานี": "Surat Thani",
    "สุรินทร์": "Surin",
    "หนองคาย": "Nong Khai",
    "หนองบัวลำภู": "Nong Bua Lamphu",
    "อ่างทอง": "Ang Thong",
    "อำนาจเจริญ": "Amnat Charoen",
    "อุดรธานี": "Udon Thani",
    "อุตรดิตถ์": "Uttaradit",
    "อุทัยธานี": "Uthai Thani",
    "อุบลราชธานี": "Ubon Ratchathani",
}


def normalize_color_th_to_en(s: str) -> str:
    if not s:
        return ""
    t = re.sub(r"\s+", "", s)
    for th, en in COLOR_MAP_TH_EN.items():
        if th.replace(" ", "") in t:
            return en
    return ""


def normalize_fuel_th_to_en(s: str) -> str:
    if not s:
        return ""
    t = s.replace(" ", "").lower()
    # รองรับทั้งไทยและอังกฤษ
    for th, en in FUEL_MAP_TH_EN.items():
        key = th.replace(" ", "").lower()
        if key in t:
            return en
    if "diesel" in t:
        return "Diesel"
    if "benzine" in t or "benzin" in t:
        return "Benzine"
    if "hybrid" in t:
        return "Hybrid"
    if "ev" in t or "electric" in t:
        return "EV"
    return ""


def normalize_transmission_th_to_en(s: str) -> str:
    if not s:
        return ""
    t = s.lower().replace(" ", "")
    for th, en in TRANSMISSION_MAP_TH_EN.items():
        key = th.lower().replace(" ", "")
        if key in t:
            return en
    if "manual" in t or "mt" in t:
        return "Manual"
    if "auto" in t or "at" in t or "automatic" in t:
        return "Automatic"
    return ""


def normalize_body_type_th_to_en(s: str) -> str:
    """แปลงชื่อประเภทรถให้เป็น EN เดียว"""
    if not s:
        return ""
    raw = s
    z = re.sub(r"\s+", "", raw)

    # แยกตาม pattern เหมือนฝั่ง Kaidee
    if "รถเก๋ง5ประตู" in z:
        return "Hatchback"
    if "รถเก๋ง4ประตู" in z:
        return "Sedan"
    if "รถเก๋ง2ประตู" in z:
        return "Coupe"
    if "เปิดประทุน" in raw:
        return "Convertible"

    if "รถSUV" in z or re.search(r"\bSUV\b", raw):
        return "SUV"
    if "รถPPV" in z or re.search(r"\bPPV\b", raw):
        return "PPV"
    if "รถMPV" in z or re.search(r"\bMPV\b", raw):
        return "MPV"

    t = raw.replace(" ", "")
    for th, en in BODY_TYPE_MAP_TH_EN.items():
        if th.replace(" ", "") in t:
            return en

    return ""


def normalize_province_from_location(loc: str) -> Tuple[str, str]:
    """รับสตริงตำแหน่ง (เช่น 'ปากเกร็ด นนทบุรี') คืน (province_en, province_th_found)"""
    if not loc:
        return "", ""
    for th, en in PROVINCE_MAP_TH_EN.items():
        if th in loc:
            return en, th
    t = loc.strip()
    if t in PROVINCE_MAP_TH_EN:
        return PROVINCE_MAP_TH_EN[t], t
    return "", ""


# ----------------- utils เดิม -----------------
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
    if a_tag is None:
        return False
    if a_tag.select_one("p.MuiTypography-root.css-1m41lnq"):
        return True
    return "ขายแล้ว" in a_tag.get_text(" ", strip=True)


def collect_links(driver, limit: int, exclude_sold: bool = True) -> List[str]:
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

    print(f"[RODDONJAI] collected total={kept+sold} kept={kept} sold_skipped={sold}")
    return links[:limit]


def extract_year(text: str) -> Optional[int]:
    m = re.search(r"(\d{4})", text or "")
    return int(m.group(1)) if m else None


# ----------------- parse page -----------------
def parse_detail(driver, url: str, debug: bool = False) -> Dict:
    """ดึงข้อมูลจากหน้า detail ของ RodDonJai แล้ว map เป็นโครงเดียวกับที่ CARCOM ใช้"""

    soup = BeautifulSoup(driver.page_source, "html.parser")

    def sel_text(selector, default=""):
        el = soup.select_one(selector)
        return (el.get_text(strip=True) if el else default) or default

    # ------------- ชื่อรถ -------------
    title = (
        sel_text(".css-ldavcx p")
        or sel_text(".mui-ldavcx p")
        or sel_text("h1,h2,.jss420")
        or "ไม่พบชื่อรุ่น"
    )

    # ------------- ราคา -------------
    raw_price = ""

    if not raw_price:
        raw_price = sel_text(
            "p.MuiTypography-root.MuiTypography-body1.css-13bl6la"
        ) or sel_text("p.MuiTypography-root.MuiTypography-body1.mui-13bl6la")

    if not raw_price:
        raw_price = sel_text("p.MuiTypography-subtitle1.jss275")

    if not raw_price:
        for p in soup.select("p"):
            t = p.get_text(strip=True)
            if re.search(r"\d{2,3}[.,]\d{3}", t):
                raw_price = t
                break

    price_clean = clean_money(raw_price) if raw_price else ""
    price_int = to_int(price_clean)

    # ------------- ตารางสเปก -------------
    specs: Dict[str, str] = {}
    for row in soup.select(
        ".MuiCollapse-wrapperInner .MuiGrid-item .d-flex.justify-content-between.mb-1"
    ):
        ps = row.select("p")
        if len(ps) >= 2:
            k = ps[0].get_text(strip=True)
            v = ps[1].get_text(strip=True)
            if k and v:
                specs[k] = v

    # ------------- ผู้ขาย -------------
    seller = sel_text("p.mui-12zbq1l") or specs.get("ผู้ขาย") or None

    # ------------- จังหวัด / ที่อยู่ -------------
    province_raw = sel_text("p.css-1ijcpbd")
    if not province_raw:
        province_raw = (
            sel_text("div.jss197 p.mui-1frg2by")
            or sel_text("div.jss116 p.mui-1frg2by")
            or sel_text("p.mui-1frg2by")
        )

    prov_en, prov_th = normalize_province_from_location(province_raw or "")
    province = prov_en or province_raw or None

    # ------------- เลขไมล์ -------------
    mileage_km: Optional[int] = None

    if "เลขไมล์" in specs:
        m = re.search(r"([\d,]+)", specs["เลขไมล์"])
        if m:
            mileage_km = to_int(m.group(1))

    if mileage_km is None:
        block = soup.find("div", class_="mui-1rx0p6b")
        if block:
            label = block.find("p", string=lambda x: x and "เลขไมล์" in x)
            if label:
                val_p = label.find_next("p")
                if val_p:
                    mileage_km = to_int(val_p.get_text(strip=True))

    if mileage_km is not None:
        specs.setdefault("เลขไมล์", f"{mileage_km:,} กม.")
    else:
        specs.setdefault("เลขไมล์", "—")

        # ------------- รูปภาพ -------------
    image_url = None


    main_img = soup.select_one(
        '.slick-slider.slider.car-profile div.slick-slide[data-index="0"] img[src*="WATERMARK"]'
    )


    if not main_img:
        main_img = soup.select_one(
            '.slick-slider.slider.car-profile div.slick-slide:not(.slick-cloned) img[src*="WATERMARK"]'
        )

    if main_img:
        src = (main_img.get("src") or "").strip()
        if src.startswith("http"):
            image_url = src


    if not image_url:
        for im in soup.select('img[src*="WATERMARK"]'):
            src = (im.get("src") or "").strip()
            if src.startswith("http"):
                image_url = src
                break



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


    year = None
    for key in ["ปี", "ปีผลิต", "ปีจดทะเบียน", "ปีที่จดทะเบียน"]:
        if key in specs:
            year = extract_year(specs.get(key) or "")
            if year:
                break
    if not year:
        year = extract_year(title)

    # ------------- Normalization: fuel / color / body / gear -------------
    # fuel: ใช้จาก "ประเภทเครื่องยนต์" หรือ "เชื้อเพลิง" ถ้ามี
    fuel_val_raw = (specs.get("ประเภทเครื่องยนต์") or specs.get("เชื้อเพลิง") or "").strip()
    fuel_en = normalize_fuel_th_to_en(fuel_val_raw)
    fuel_display = fuel_en or fuel_val_raw
    if fuel_display:
        specs["ประเภทเครื่องยนต์"] = fuel_display
        specs["เชื้อเพลิง"] = fuel_display

    # color
    color_th = (specs.get("สี") or "").strip()
    color_en = normalize_color_th_to_en(color_th)
    color_display = color_en or color_th
    if color_display:
        specs["สี"] = color_display

    # body type
    body_main_th = (specs.get("ประเภท") or specs.get("ประเภทรถ") or "").strip()
    body_sub_th = (specs.get("ประเภทย่อย") or "").strip()
    body_source = body_sub_th or body_main_th
    body_en = normalize_body_type_th_to_en(body_source or body_main_th)
    body_display = body_en or body_source or body_main_th
    if body_display:
        specs["ประเภทรถ"] = body_display
        specs["ประเภท"] = body_display
    # ไม่อยากให้โชว์วงเล็บไทยซ้ำ
    specs["ประเภทย่อย"] = ""

    # transmission
    gear_raw = (specs.get("เกียร์") or "").strip()
    gear_en = normalize_transmission_th_to_en(gear_raw)
    gear_display = gear_en or gear_raw
    if gear_display:
        specs["เกียร์"] = gear_display

    # ------------- เชื้อเพลิง (ใช้ค่าที่ normalize แล้ว) -------------
    fuel_type = fuel_display
    fuel_key = "ประเภทเครื่องยนต์" if fuel_type else ""
    fuel_method = "specs" if fuel_type else "not-found"

    # ------------- attrs_json -------------
    attrs: Dict[str, object] = {
        "ผู้ขาย": seller or "RODDONJAI",
        "ชื่อรุ่น": title,
        "ราคา(บาท)": price_clean or raw_price or "",
        "เลขไมล์(กม.)": f"{mileage_km:,}" if mileage_km is not None else "",
        "จังหวัด": province or "",
        "จังหวัด_th": prov_th or "",
        "สเปกย่อย": specs,
        "body_type_th": body_source or body_main_th,
        "body_type_en": body_en or "",
        "body_type_normalized": (body_en or body_display or "").lower(),
        "color_th": color_th,
        "color_en": color_en or "",
        "color_normalized": (color_display or "").lower(),
        "transmission_th": gear_raw,
        "transmission_en": gear_en or "",
        "transmission_normalized": (gear_display or "").lower(),
    }

    if fuel_type:
        attrs["ประเภทเชื้อเพลิง"] = fuel_type
        attrs["เชื้อเพลิง"] = fuel_type
        attrs["fuel_type_normalized"] = fuel_type.lower()
        attrs["fuel_type_th"] = fuel_val_raw
        attrs["fuel_type_en"] = fuel_en or ""
        if isinstance(attrs.get("สเปกย่อย"), dict):
            attrs["สเปกย่อย"].setdefault("เชื้อเพลิง", fuel_type)

    debug_fuel = {"value": fuel_type, "key": fuel_key, "method": fuel_method}

    if debug:
        print("======== RODDONJAI DETAIL DEBUG ========")
        print(f"url           : {url}")
        print(f"title         : {title!r}")
        print(f"raw_price     : {raw_price!r}")
        print(f"price_clean   : {price_clean!r}")
        print(f"price_int     : {price_int!r}")
        print(f"seller        : {seller!r}")
        print(f"province_raw  : {province_raw!r}")
        print(f"province_th   : {prov_th!r}")
        print(f"province_en   : {province!r}")
        print(f"brand         : {brand!r}")
        print(f"model         : {model!r}")
        print(f"year          : {year!r}")
        print(f"mileage_km    : {mileage_km!r}")
        print(f"image_url     : {image_url!r}")
        print(f"fuel_raw      : {fuel_val_raw!r}")
        print(f"fuel_en       : {fuel_en!r}")
        print(f"fuel_display  : {fuel_display!r}")
        print(f"gear_raw      : {gear_raw!r}")
        print(f"gear_en       : {gear_en!r}")
        print(f"gear_display  : {gear_display!r}")
        print(f"color_th      : {color_th!r}")
        print(f"color_en      : {color_en!r}")
        print(f"body_main_th  : {body_main_th!r}")
        print(f"body_sub_th   : {body_sub_th!r}")
        print(f"body_en       : {body_en!r}")
        print(f"body_display  : {body_display!r}")
        print(f"specs_keys    : {list(specs.keys())}")
        print(f"debug_fuel    : {debug_fuel}")
        print("========================================")

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
    p.add_argument(
        "--debug-detail",
        action="store_true",
        help="พิมพ์ค่าทุก field ที่ดึงได้จากแต่ละ detail page",
    )

    args = p.parse_args()
    raw_q = (args.q or "").strip()
    q = raw_q
    exclude_sold = not args.include_sold

    driver = None
    created = 0

    try:
        driver = build_driver(args.chromedriver, args.headless)

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

        wait_any(driver, ["#scrollDivResult", ".jss249"])
        time.sleep(1.0)

        def count_cards():
            tmp = BeautifulSoup(driver.page_source, "html.parser")
            return len(tmp.select('a[href^="/service/car-detail/"]'))

        auto_scroll_until_stable(driver, count_cards, cooldown=1.0, stable_ticks=3)

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

                    try:
                        wait_any(
                            driver,
                            [
                                ".css-ldavcx",
                                ".mui-ldavcx",
                                ".MuiCollapse-wrapperInner",
                                "h1",
                                ".jss420",
                            ],
                            timeout=15,
                        )
                    except TimeoutException as te:
                        print(
                            f"#{i} warn: Timeout waiting detail DOM "
                            f"({type(te).__name__}) -> {link}"
                        )
                        time.sleep(2.0)

                    data = parse_detail(driver, link, debug=args.debug_detail)

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
                            if words[0] not in blob:
                                print(f"#{i} skip kw (not match '{raw_q}') -> {link}")
                                continue
                        else:
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
                    print(f"#{i} error: {type(e).__name__}: {e}")
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
