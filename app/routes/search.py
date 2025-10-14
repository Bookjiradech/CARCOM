from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import select, delete
from app.db import SessionLocal
from app.models import SearchSession, SearchSessionCar, CarCache
from app.services.credits import consume_one_credit
from app.services.search import pick_cars

bp = Blueprint("search", __name__, template_folder="../templates/search")

@bp.get("/search")
@login_required
def search_form():
    return render_template("search/form.html")

@bp.post("/search/start")
@login_required
def search_start():
    filters = {
        "budget_max": request.form.get("budget_max"),
        "brand": request.form.get("brand"),
        "min_year": request.form.get("min_year"),
    }

    db = SessionLocal()
    try:
        # ตัดเครดิต 1 ครั้ง
        if not consume_one_credit(db, current_user.id):
            db.rollback()
            flash("เครดิตไม่เพียงพอ กรุณาซื้อแพ็กเกจ", "error")
            return redirect(url_for("shop.list_packages"))

        # สร้าง search session
        ses = SearchSession(user_id=current_user.id, filters=filters, used_credits=1)
        db.add(ses)
        db.flush()  # ได้ ses.id

        # เลือกรถ และบันทึกผลใน SearchSessionCar
        cars = pick_cars(db, filters, limit=12)
        for idx, car in enumerate(cars, start=1):
            db.add(SearchSessionCar(session_id=ses.id, car_id=car.id, rank=idx))

        db.commit()
        return redirect(url_for("shop.search_view", session_id=ses.id))
    finally:
        db.close()

@bp.get("/search/<int:session_id>")
@login_required
def search_view(session_id: int):
    db = SessionLocal()
    try:
        ses = db.get(SearchSession, session_id)
        if not ses or ses.user_id != current_user.id:
            flash("ไม่พบการค้นหา", "error")
            return redirect(url_for("shop.search_form"))

        # ดึงรายการรถของรอบล่าสุด (เราเก็บทับในตารางเดิมแล้ว)
        q = (
            select(CarCache, SearchSessionCar.rank)
            .join(SearchSessionCar, SearchSessionCar.car_id == CarCache.id)
            .where(SearchSessionCar.session_id == session_id)
            .order_by(SearchSessionCar.rank.asc())
        )
        rows = db.execute(q).all()
        cars = [{"rank": r.rank, "car": c} for (c, r) in rows]

        return render_template("search/results.html", session=ses, cars=cars)
    finally:
        db.close()

@bp.post("/search/<int:session_id>/again")
@login_required
def search_again(session_id: int):
    db = SessionLocal()
    try:
        ses = db.get(SearchSession, session_id)
        if not ses or ses.user_id != current_user.id:
            flash("ไม่พบการค้นหา", "error")
            return redirect(url_for("shop.search_form"))

        # ตัดเครดิตอีก 1 ครั้ง
        if not consume_one_credit(db, current_user.id):
            db.rollback()
            flash("เครดิตไม่พอสำหรับค้นหาใหม่ กรุณาซื้อแพ็กเกจ", "error")
            return redirect(url_for("shop.list_packages"))

        # ลบรายการรถเดิมของ session นี้
        db.execute(delete(SearchSessionCar).where(SearchSessionCar.session_id == ses.id))

        # เลือกรถชุดใหม่
        cars = pick_cars(db, ses.filters or {}, limit=12)
        for idx, car in enumerate(cars, start=1):
            db.add(SearchSessionCar(session_id=ses.id, car_id=car.id, rank=idx))

        # เพิ่มตัวนับเครดิตที่ใช้ใน session
        ses.used_credits += 1
        db.add(ses)

        db.commit()
        return redirect(url_for("shop.search_view", session_id=ses.id))
    finally:
        db.close()
