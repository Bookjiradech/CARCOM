# backend/scripts/init_db_once.py
import os, sys
from dotenv import load_dotenv

# ให้ import app.* ได้ไม่ว่าเราจะรันจากโฟลเดอร์ไหน
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# โหลด .env ก่อน import engine (สำคัญถ้า DB_URL เก็บไว้ใน .env)
load_dotenv()

from app.db import Base, engine
from app import models  # ต้อง import ให้ Base รู้จักทุกโมเดลก่อน create_all()

if __name__ == "__main__":
    print("Creating tables if not exist ...")
    Base.metadata.create_all(bind=engine)
    print("Done.")
