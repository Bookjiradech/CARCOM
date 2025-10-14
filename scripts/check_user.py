import os, sys
from dotenv import load_dotenv

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))

from app.db import SessionLocal
from app.models import User

db = SessionLocal()
u = db.query(User).filter_by(username="book").first()
print("user:", u.username if u else None, "is_admin:", getattr(u, "is_admin", None))
db.close()
