import os
from dotenv import load_dotenv
from flask import app

def load_config(app):
    load_dotenv()
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "devkey")

    # Uploads
    upload_dir = os.path.join(os.getcwd(), os.getenv("UPLOAD_DIR", "uploads/slips"))
    os.makedirs(upload_dir, exist_ok=True)
    app.config["UPLOAD_DIR"] = upload_dir
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
    app.config["ALLOWED_EXTENSIONS"] = {"jpg", "jpeg", "png", "pdf"}

    # ต้องรอแอดมินอนุมัติเป็นค่าเริ่มต้น (override ได้ด้วย ENV)
    app.config["AUTO_APPROVE_PAYMENT"] = os.getenv("AUTO_APPROVE_PAYMENT", "false").lower() == "true"

    # ===== Scraper =====
    # รองรับทั้งชื่อใหม่และชื่อเก่าใน .env
    chromedriver = (
        os.getenv("SCRAPER_CHROMEDRIVER")
        or os.getenv("CHROMEDRIVER_PATH")
        or ""
    )
    app.config["SCRAPER_CHROMEDRIVER"] = chromedriver

    app.config["SCRAPER_HEADLESS"] = os.getenv("SCRAPER_HEADLESS", "true").lower() == "true"

    # จำนวนที่ "สแครป" ต่อแหล่ง 
    app.config["SCRAPER_LIMIT"] = int(os.getenv("SCRAPER_LIMIT", "20"))
    # จำนวนที่ "แสดงผล" บนหน้า (ถ้าไม่ตั้ง จะเท่ากับ SCRAPER_LIMIT)
    app.config["SEARCH_DISPLAY_LIMIT"] = int(
        os.getenv("SEARCH_DISPLAY_LIMIT", os.getenv("SCRAPER_LIMIT", "20"))
    )

    # เลือกแหล่ง (คอมม่า)
    app.config["SCRAPER_SOURCES"] = os.getenv("SCRAPER_SOURCES", "kaidee,carsome,one2car")

    # เสริมดีบัก/timeout
    app.config["SCRAPER_DEBUG_DUMP"] = os.getenv("SCRAPER_DEBUG_DUMP", "false").lower() == "true"
    app.config["SCRAPER_TIMEOUT_SEC"] = int(
        os.getenv("SCRAPER_TIMEOUT_SEC") or os.getenv("SCRAPER_TIMEOUT") or "480"
    )

    # Security Questions (เลือกได้จากดรอปดาวน์)
    app.config["SECURITY_QUESTIONS"] = [
        "ชื่อสัตว์เลี้ยงตัวแรกของคุณคืออะไร?",
        "โรงเรียนประถมของคุณชื่ออะไร?",
        "บ้านเกิดของคุณอยู่จังหวัดอะไร?",
        "อาหารจานโปรดของคุณคืออะไร?",
        "ชื่อเล่นของคุณตอนเด็กคืออะไร?",
    ]
    
    # Admins (รายชื่อผู้ใช้ที่เป็นผู้ดูแลระบบ)
    app.config["ADMIN_USERNAMES"] = [
        u.strip() for u in os.getenv("ADMIN_USERNAMES", "admin").split(",") if u.strip()
    ]
