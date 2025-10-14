# -*- coding: utf-8 -*-
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from passlib.hash import bcrypt
from sqlalchemy import select, func, or_, desc

from app.db import SessionLocal
from app.models import User, SecurityAnswer, UserPackage, Payment
from passlib.hash import bcrypt

bp = Blueprint("auth", __name__, template_folder="../templates/auth")


# ---------- helpers ----------
def normalize_answer(s: str) -> str:
    return (s or "").strip().lower()


def _active_userpackages_q(db, user_id: int):
    return (
        select(UserPackage)
        .where(
            UserPackage.user_id == user_id,
            UserPackage.status == "active",
            or_(UserPackage.end_at.is_(None), UserPackage.end_at > func.now()),
        )
        .order_by(UserPackage.id)
    )


# ---------- Register ----------
@bp.get("/register")
def register():
    return render_template(
        "auth/register.html",
        questions=current_app.config.get("SECURITY_QUESTIONS", []),
    )


@bp.post("/register")
def register_post():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")

    qs_config = current_app.config.get("SECURITY_QUESTIONS", []) or []

    def pick_text_from_id(val: str) -> str:
        try:
            qid = int(val)
        except (TypeError, ValueError):
            return ""
        # รองรับทั้ง 1-based และ 0-based
        if 1 <= qid <= len(qs_config):
            return qs_config[qid - 1]
        if 0 <= qid < len(qs_config):
            return qs_config[qid]
        return ""

    # รับจากสองรูปแบบฟอร์ม
    q1 = pick_text_from_id(request.form.get("security_q1"))
    q2 = pick_text_from_id(request.form.get("security_q2"))
    if not q1:
        q1 = (request.form.get("question1") or "").strip()
    if not q2:
        q2 = (request.form.get("question2") or "").strip()

    a1 = request.form.get("security_a1") or request.form.get("answer1") or ""
    a2 = request.form.get("security_a2") or request.form.get("answer2") or ""

    if not username or not password or not confirm or not q1 or not a1 or not q2 or not a2:
        flash("กรุณากรอกข้อมูลให้ครบ", "error")
        return redirect(url_for("auth.register"))

    if len(password) < 8:
        flash("รหัสผ่านควรยาวอย่างน้อย 8 ตัวอักษร", "error")
        return redirect(url_for("auth.register"))

    if password != confirm:
        flash("รหัสผ่านยืนยันไม่ตรงกัน", "error")
        return redirect(url_for("auth.register"))

    db = SessionLocal()
    try:
        user = User(username=username, password_hash=bcrypt.hash(password))
        db.add(user)
        db.flush()

        def _norm(s: str) -> str:
            return (s or "").strip().lower()

        sas = [
            SecurityAnswer(user_id=user.id, question=q1, answer_hash=bcrypt.hash(_norm(a1))),
            SecurityAnswer(user_id=user.id, question=q2, answer_hash=bcrypt.hash(_norm(a2))),
        ]
        db.add_all(sas)

        db.commit()
        flash("สมัครสมาชิกสำเร็จ", "success")
        return redirect(url_for("auth.login"))
    except Exception as e:
        db.rollback()
        flash(f"สมัครไม่สำเร็จ: {e}", "error")
        return redirect(url_for("auth.register"))
    finally:
        db.close()


# ---------- Login / Logout ----------
@bp.get("/login")
def login():
    return render_template("auth/login.html")


@bp.post("/login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password", "")
    admin_mode = (request.form.get("admin") == "1")  # ปุ่มผู้ดูแลส่ง admin=1

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if not user or not bcrypt.verify(password, user.password_hash):
            flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", "error")
            return redirect(url_for("auth.login"))

        if user.status != "active":
            flash("บัญชีถูกระงับชั่วคราว", "error")
            return redirect(url_for("auth.login"))

        if admin_mode and not getattr(user, "is_admin", False):
            flash("บัญชีนี้ไม่มีสิทธิ์ผู้ดูแลระบบ", "error")
            return redirect(url_for("auth.login"))

        login_user(user)
        flash("เข้าสู่ระบบสำเร็จ", "success")
        return redirect(url_for("admin.dashboard" if admin_mode else "home"))
    finally:
        db.close()


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("ออกจากระบบแล้ว", "success")
    return redirect(url_for("auth.login"))


# ---------- Dashboard shortcut ----------
@bp.get("/dashboard")
@login_required
def dashboard():
    return redirect(url_for("auth.account"))


# ---------- My Account ----------
@bp.get("/account")
@login_required
def account():
    db = SessionLocal()
    try:
        # เครดิตคงเหลือ
        credits_stmt = (
            select(func.coalesce(func.sum(UserPackage.remaining_calls), 0))
            .where(
                UserPackage.user_id == current_user.id,
                UserPackage.status == "active",
                or_(UserPackage.end_at.is_(None), UserPackage.end_at > func.now()),
            )
        )
        total_credits = int(db.execute(credits_stmt).scalar() or 0)

        # วันคงเหลือ: ใช้ end_at ที่ไกลที่สุดในแพ็กเกจที่ยัง active
        ups = db.execute(_active_userpackages_q(db, current_user.id)).scalars().all()
        max_end = None
        for up in ups:
            if up.end_at:
                if (max_end is None) or (up.end_at > max_end):
                    max_end = up.end_at

        remaining_days = None
        if max_end:
            now = datetime.utcnow().replace(tzinfo=None)
            end_naive = max_end.replace(tzinfo=None)
            delta = end_naive - now
            remaining_days = max(0, delta.days)

        # ประวัติการชำระเงินของผู้ใช้
        payments = db.execute(
            select(Payment)
            .where(Payment.user_id == current_user.id)
            .order_by(desc(Payment.id))
        ).scalars().all()

        return render_template(
            "auth/account.html",
            total_credits=total_credits,
            remaining_days=remaining_days,
            payments=payments,
        )
    finally:
        db.close()


# ----- Reset password จากหน้า Account -----
@bp.post("/account/reset_password")
@login_required
def account_reset_password():
    old_password = request.form.get("old_password", "")
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm", "")

    if not new_password or len(new_password) < 8:
        flash("รหัสผ่านใหม่ควรยาวอย่างน้อย 8 ตัวอักษร", "error")
        return redirect(url_for("auth.account"))
    if new_password != confirm:
        flash("รหัสผ่านยืนยันไม่ตรงกัน", "error")
        return redirect(url_for("auth.account"))

    db = SessionLocal()
    try:
        user = db.get(User, current_user.id)
        if not user or not bcrypt.verify(old_password, user.password_hash):
            flash("รหัสผ่านเดิมไม่ถูกต้อง", "error")
            return redirect(url_for("auth.account"))

        user.password_hash = bcrypt.hash(new_password)
        db.add(user)
        db.commit()
        flash("เปลี่ยนรหัสผ่านเรียบร้อยแล้ว", "success")
        return redirect(url_for("auth.account"))
    finally:
        db.close()


# ----- Reset security questions จากหน้า Account -----
@bp.post("/account/reset_security")
@login_required
def account_reset_security():
    q1 = (request.form.get("question1") or "").strip()
    a1 = request.form.get("answer1", "")
    q2 = (request.form.get("question2") or "").strip()
    a2 = request.form.get("answer2", "")

    if not q1 or not a1 or not q2 or not a2:
        flash("กรุณากรอกคำถามและคำตอบให้ครบ", "error")
        return redirect(url_for("auth.account"))

    db = SessionLocal()
    try:
        # ลบของเก่า (เอาแค่ 2 แถวไว้เสมอ)
        olds = db.execute(
            select(SecurityAnswer).where(SecurityAnswer.user_id == current_user.id)
        ).scalars().all()
        for r in olds:
            db.delete(r)

        db.flush()

        sa1 = SecurityAnswer(
            user_id=current_user.id,
            question=q1,
            answer_hash=bcrypt.hash(normalize_answer(a1)),
        )
        sa2 = SecurityAnswer(
            user_id=current_user.id,
            question=q2,
            answer_hash=bcrypt.hash(normalize_answer(a2)),
        )
        db.add_all([sa1, sa2])
        db.commit()
        flash("อัปเดตคำถามความปลอดภัยเรียบร้อยแล้ว", "success")
        return redirect(url_for("auth.account"))
    finally:
        db.close()


# ---------- Forgot password flow ----------
@bp.get("/forgot")
def forgot():
    return render_template("auth/forgot.html")


@bp.post("/forgot")
def forgot_post():
    username = (request.form.get("username") or "").strip()
    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if user:
            qrows = db.execute(
                select(SecurityAnswer)
                .where(SecurityAnswer.user_id == user.id)
                .order_by(SecurityAnswer.id)
            ).scalars().all()

            qrows = qrows[:2]
            questions_ok = (
                len(qrows) == 2
                and all((r.question or "").strip() for r in qrows)
            )
            if questions_ok:
                session["fp_user_id"] = user.id
                session["fp_qids"] = [r.id for r in qrows]
                return redirect(url_for("auth.forgot_verify"))
            else:
                flash("บัญชีนี้ยังไม่ได้ตั้งคำถามความปลอดภัยหรือข้อมูลไม่สมบูรณ์ กรุณาเข้าสู่ระบบและตั้งค่าในหน้า Account > Security ก่อน", "error")
                return redirect(url_for("auth.forgot"))

        flash("ถ้าชื่อผู้ใช้งานถูกต้อง ระบบจะพาไปขั้นตอนถัดไป", "info")
        return redirect(url_for("auth.forgot"))
    finally:
        db.close()



@bp.get("/forgot/verify")
def forgot_verify():
    user_id = session.get("fp_user_id")
    qids = session.get("fp_qids", [])
    questions = []
    if user_id and qids:
        db = SessionLocal()
        try:
            rows = db.execute(
                select(SecurityAnswer).where(SecurityAnswer.id.in_(qids))
            ).scalars().all()
            questions = [ (r.question or "").strip() for r in rows ]
        finally:
            db.close()

    if not user_id or len(questions) < 2 or any(q == "" for q in questions):
        flash("หมดอายุการยืนยัน หรือยังไม่ได้ตั้งคำถามความปลอดภัย", "error")
        return redirect(url_for("auth.forgot"))

    return render_template("auth/forgot_verify.html", questions=questions)



@bp.post("/forgot/verify")
def forgot_verify_post():
    user_id = session.get("fp_user_id")
    qids = session.get("fp_qids", [])
    if not user_id or not qids:
        flash("หมดอายุการยืนยัน กรุณาเริ่มใหม่", "error")
        return redirect(url_for("auth.forgot"))

    a1 = request.form.get("answer1", "")
    a2 = request.form.get("answer2", "")
    answers = [normalize_answer(a1), normalize_answer(a2)]

    db = SessionLocal()
    try:
        rows = db.execute(select(SecurityAnswer).where(SecurityAnswer.id.in_(qids))).scalars().all()
        ok = True
        for idx, row in enumerate(rows):
            if idx >= len(answers) or not bcrypt.verify(answers[idx], row.answer_hash):
                ok = False
                break
        if not ok:
            flash("คำตอบไม่ถูกต้อง", "error")
            return redirect(url_for("auth.forgot_verify"))

        session["fp_verified"] = True
        flash("ยืนยันสำเร็จ กรุณาตั้งรหัสผ่านใหม่", "success")
        return redirect(url_for("auth.forgot_reset"))
    finally:
        db.close()


@bp.get("/forgot/reset")
def forgot_reset():
    if not session.get("fp_verified"):
        flash("กรุณายืนยันคำถามความปลอดภัยก่อน", "error")
        return redirect(url_for("auth.forgot"))
    return render_template("auth/forgot_reset.html")


@bp.post("/forgot/reset")
def forgot_reset_post():
    if not session.get("fp_verified"):
        flash("หมดอายุการยืนยัน กรุณาเริ่มใหม่", "error")
        return redirect(url_for("auth.forgot"))

    new_password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")
    if not new_password or len(new_password) < 8:
        flash("รหัสผ่านควรยาวอย่างน้อย 8 ตัวอักษร", "error")
        return redirect(url_for("auth.forgot_reset"))
    if new_password != confirm:
        flash("รหัสผ่านยืนยันไม่ตรงกัน", "error")
        return redirect(url_for("auth.forgot_reset"))

    user_id = session.get("fp_user_id")
    db = SessionLocal()
    try:
        user = db.get(User, int(user_id)) if user_id else None
        if not user:
            flash("ไม่พบบัญชีผู้ใช้", "error")
            return redirect(url_for("auth.forgot"))

        user.password_hash = bcrypt.hash(new_password)
        db.add(user)
        db.commit()

        session.pop("fp_user_id", None)
        session.pop("fp_qids", None)
        session.pop("fp_verified", None)

        flash("ตั้งรหัสผ่านใหม่เรียบร้อยแล้ว", "success")
        return redirect(url_for("auth.login"))
    finally:
        db.close()
