# scripts/seed_cars.py
from app import create_app
from app.db import SessionLocal
from app.models import CarCache

app = create_app()

def run():
    db = SessionLocal()
    try:
        demo = [
            dict(source="demo", source_id="1", title="Toyota Yaris 1.2 (2019)", brand="Toyota", model="Yaris",   year=2019, price_thb=379000, mileage_km=45000,  province="กรุงเทพ",   url=None, image_url=None),
            dict(source="demo", source_id="2", title="Honda Civic 1.8 (2017)",  brand="Honda",  model="Civic",   year=2017, price_thb=589000, mileage_km=80000,  province="นนทบุรี",  url=None, image_url=None),
            dict(source="demo", source_id="3", title="Mazda 2 1.3 (2020)",     brand="Mazda",  model="2",       year=2020, price_thb=439000, mileage_km=30000,  province="ปทุมธานี", url=None, image_url=None),
            dict(source="demo", source_id="4", title="Toyota Fortuner (2016)", brand="Toyota", model="Fortuner", year=2016, price_thb=799000, mileage_km=120000, province="ชลบุรี",   url=None, image_url=None),
        ]
        for d in demo:
            exists = db.query(CarCache).filter_by(source="demo", source_id=d["source_id"]).first()
            if not exists:
                db.add(CarCache(**d))
        db.commit()
        print("Seed cars OK")
    finally:
        db.close()

if __name__ == "__main__":
    run()
