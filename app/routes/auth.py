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
        # Support both 1-based and 0-based indices
        if 1 <= qid <= len(qs_config):
            return qs_config[qid - 1]
        if 0 <= qid < len(qs_config):
            return qs_config[qid]
        return ""

    # Accept both form styles
    q1 = pick_text_from_id(request.form.get("security_q1"))
    q2 = pick_text_from_id(request.form.get("security_q2"))
    if not q1:
        q1 = (request.form.get("question1") or "").strip()
    if not q2:
        q2 = (request.form.get("question2") or "").strip()

    a1 = request.form.get("security_a1") or request.form.get("answer1") or ""
    a2 = request.form.get("security_a2") or request.form.get("answer2") or ""

    if not username or not password or not confirm or not q1 or not a1 or not q2 or not a2:
        flash("Please fill in all required fields.", "error")
        return redirect(url_for("auth.register"))

    if len(password) < 8:
        flash("Password should be at least 8 characters.", "error")
        return redirect(url_for("auth.register"))

    if password != confirm:
        flash("Password confirmation does not match.", "error")
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
        flash("Registration successful.", "success")
        return redirect(url_for("auth.login"))
    except Exception as e:
        db.rollback()
        flash(f"Registration failed: {e}", "error")
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
    admin_mode = (request.form.get("admin") == "1")  # admin toggle sends admin=1

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if not user or not bcrypt.verify(password, user.password_hash):
            flash("Invalid username or password.", "error")
            return redirect(url_for("auth.login"))

        if user.status != "active":
            flash("Account is temporarily suspended.", "error")
            return redirect(url_for("auth.login"))

        if admin_mode and not getattr(user, "is_admin", False):
            flash("This account has no admin privileges.", "error")
            return redirect(url_for("auth.login"))

        login_user(user)
        flash("Logged in successfully.", "success")
        return redirect(url_for("admin.dashboard" if admin_mode else "home"))
    finally:
        db.close()


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out.", "success")
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
        # total credits
        credits_stmt = (
            select(func.coalesce(func.sum(UserPackage.remaining_calls), 0))
            .where(
                UserPackage.user_id == current_user.id,
                UserPackage.status == "active",
                or_(UserPackage.end_at.is_(None), UserPackage.end_at > func.now()),
            )
        )
        total_credits = int(db.execute(credits_stmt).scalar() or 0)

        # remaining time: max end_at among active packages
        ups = db.execute(_active_userpackages_q(db, current_user.id)).scalars().all()
        max_end = None
        for up in ups:
            if up.end_at:
                if (max_end is None) or (up.end_at > max_end):
                    max_end = up.end_at

        remaining_days = None
        remaining_seconds = None
        if max_end:
            # ใช้เวลาแบบ timezone-aware ทั้งคู่ (ถือว่า end_at เป็น UTC ถ้าเป็น naive)
            now_utc = datetime.now(timezone.utc)
            end_at = max_end if max_end.tzinfo else max_end.replace(tzinfo=timezone.utc)

            delta = end_at - now_utc
            total_secs = int(delta.total_seconds())
            if total_secs < 0:
                total_secs = 0

            remaining_seconds = total_secs
            remaining_days = max(0, delta.days)

        # user's payment history
        payments = db.execute(
            select(Payment)
            .where(Payment.user_id == current_user.id)
            .order_by(desc(Payment.id))
        ).scalars().all()

        return render_template(
            "auth/account.html",
            total_credits=total_credits,
            remaining_days=remaining_days,         # คงไว้เพื่อ compatibility เดิม
            remaining_seconds=remaining_seconds,   # >>> คีย์ใหม่สำหรับเคาน์ต์ดาวน์
            payments=payments,
        )
    finally:
        db.close()


# ----- Reset password from Account page -----
@bp.post("/account/reset_password")
@login_required
def account_reset_password():
    old_password = request.form.get("old_password", "")
    new_password = request.form.get("new_password", "")
    confirm = request.form.get("confirm", "")

    if not new_password or len(new_password) < 8:
        flash("New password should be at least 8 characters.", "error")
        return redirect(url_for("auth.account"))
    if new_password != confirm:
        flash("Password confirmation does not match.", "error")
        return redirect(url_for("auth.account"))

    db = SessionLocal()
    try:
        user = db.get(User, current_user.id)
        if not user or not bcrypt.verify(old_password, user.password_hash):
            flash("Current password is incorrect.", "error")
            return redirect(url_for("auth.account"))

        user.password_hash = bcrypt.hash(new_password)
        db.add(user)
        db.commit()
        flash("Password changed successfully.", "success")
        return redirect(url_for("auth.account"))
    finally:
        db.close()


# ----- Reset security Q&A from Account page -----
@bp.post("/account/reset_security")
@login_required
def account_reset_security():
    q1 = (request.form.get("question1") or "").strip()
    a1 = request.form.get("answer1", "")
    q2 = (request.form.get("question2") or "").strip()
    a2 = request.form.get("answer2", "")

    if not q1 or not a1 or not q2 or not a2:
        flash("Please provide both questions and answers.", "error")
        return redirect(url_for("auth.account"))

    db = SessionLocal()
    try:
        # remove old entries (keep exactly 2 rows)
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
        flash("Security questions updated.", "success")
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
                flash("This account has not set valid security questions. Please log in and set them in Account > Security.", "error")
                return redirect(url_for("auth.forgot"))

        flash("If the username is correct, you'll be taken to the next step.", "info")
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
        flash("Verification expired or security questions not available.", "error")
        return redirect(url_for("auth.forgot"))

    return render_template("auth/forgot_verify.html", questions=questions)



@bp.post("/forgot/verify")
def forgot_verify_post():
    user_id = session.get("fp_user_id")
    qids = session.get("fp_qids", [])
    if not user_id or not qids:
        flash("Verification expired. Please start again.", "error")
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
            flash("Incorrect answers.", "error")
            return redirect(url_for("auth.forgot_verify"))

        session["fp_verified"] = True
        flash("Verified. Please set a new password.", "success")
        return redirect(url_for("auth.forgot_reset"))
    finally:
        db.close()


@bp.get("/forgot/reset")
def forgot_reset():
    if not session.get("fp_verified"):
        flash("Please verify security questions first.", "error")
        return redirect(url_for("auth.forgot"))
    return render_template("auth/forgot_reset.html")


@bp.post("/forgot/reset")
def forgot_reset_post():
    if not session.get("fp_verified"):
        flash("Verification expired. Please start again.", "error")
        return redirect(url_for("auth.forgot"))

    new_password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")
    if not new_password or len(new_password) < 8:
        flash("Password should be at least 8 characters.", "error")
        return redirect(url_for("auth.forgot_reset"))
    if new_password != confirm:
        flash("Password confirmation does not match.", "error")
        return redirect(url_for("auth.forgot_reset"))

    user_id = session.get("fp_user_id")
    db = SessionLocal()
    try:
        user = db.get(User, int(user_id)) if user_id else None
        if not user:
            flash("User not found.", "error")
            return redirect(url_for("auth.forgot"))

        user.password_hash = bcrypt.hash(new_password)
        db.add(user)
        db.commit()

        session.pop("fp_user_id", None)
        session.pop("fp_qids", None)
        session.pop("fp_verified", None)

        flash("Password has been reset. Please log in.", "success")
        return redirect(url_for("auth.login"))
    finally:
        db.close()
