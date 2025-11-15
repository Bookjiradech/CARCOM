# app/routes/admin.py
from __future__ import annotations
from datetime import datetime, timedelta, date
from calendar import monthrange

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from sqlalchemy import select, desc, func, extract
from sqlalchemy.orm import joinedload

from app.db import SessionLocal
from app.models import User, Package, Promotion, Payment, UserPackage
import os

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _admin_required(view):
    @login_required
    def wrapped(*args, **kwargs):
        if not getattr(current_user, "is_admin", False):
            flash("Admin only.", "error")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    wrapped.__name__ = view.__name__
    return wrapped


def _parse_date_val(v):
    """Try to parse a value into a date from form or database."""
    if not v:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None


def _auto_expire_promotions(db):
    """If today > end_date and status is still active, set to inactive automatically."""
    today = date.today()
    rows = db.execute(select(Promotion).where(Promotion.status == "active")).scalars().all()
    changed = 0
    for p in rows:
        ed = _parse_date_val(getattr(p, "end_date", None))
        if ed and today > ed and p.status == "active":
            p.status = "inactive"
            p.updated_at = datetime.utcnow()
            db.add(p)
            changed += 1
    if changed:
        db.commit()


# ------------------ Dashboard ------------------
@bp.get("/dashboard")
@_admin_required
def dashboard():
    """
    New dashboard:
    - Revenue filters via query params: range=monthly|yearly|all, year=YYYY, month=1-12
    - Provide summaries: rev_period_total, rev_this_year, rev_all_time
    - Provide chart data: chart_labels, chart_values
    - Keep pending/approved lists as before
    """
    db = SessionLocal()
    try:
        # ---------- aggregate stats ----------
        _auto_expire_promotions(db)
        total_users = db.execute(select(func.count(User.id))).scalar_one() or 0
        total_packages = db.execute(select(func.count(Package.id))).scalar_one() or 0
        total_promos = db.execute(select(func.count(Promotion.id))).scalar_one() or 0

        # ---------- time-range params ----------
        today = date.today()
        rg = (request.args.get("range") or "monthly").lower()  # monthly | yearly | all
        year = int(request.args.get("year") or today.year)
        month = int(request.args.get("month") or today.month)

        # English short month names
        months_th = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

        # ---------- build available years from data (fallback to last 3 years) ----------
        y_bounds = db.execute(
            select(
                func.min(extract("year", Payment.created_at)),
                func.max(extract("year", Payment.created_at)),
            ).where(Payment.status == "approved")
        ).first()
        if y_bounds and y_bounds[0] and y_bounds[1]:
            y_min, y_max = int(y_bounds[0]), int(y_bounds[1])
        else:
            y_min, y_max = year - 2, year
        years = list(range(y_min, y_max + 1))

        # ---------- base revenue summaries ----------
        rev_all_time = db.execute(
            select(func.coalesce(func.sum(Payment.total), 0))
            .where(Payment.status == "approved")
        ).scalar() or 0.0

        rev_this_year = db.execute(
            select(func.coalesce(func.sum(Payment.total), 0))
            .where(
                Payment.status == "approved",
                extract("year", Payment.created_at) == today.year,
            )
        ).scalar() or 0.0

        # ---------- chart data ----------
        chart_labels: list[str] = []
        chart_values: list[float] = []
        rev_period_total = 0.0

        if rg == "monthly":
            # daily chart for selected month
            last_day = monthrange(year, month)[1]
            rows = db.execute(
                select(
                    extract("day", Payment.created_at),
                    func.coalesce(func.sum(Payment.total), 0),
                )
                .where(
                    Payment.status == "approved",
                    extract("year", Payment.created_at) == year,
                    extract("month", Payment.created_at) == month,
                )
                .group_by(extract("day", Payment.created_at))
                .order_by(extract("day", Payment.created_at))
            ).all()
            sums_by_day = {int(d): float(s) for d, s in rows}

            chart_labels = [f"{d} {months_th[month-1]}" for d in range(1, last_day + 1)]
            chart_values = [sums_by_day.get(d, 0.0) for d in range(1, last_day + 1)]
            rev_period_total = sum(chart_values)

        elif rg == "yearly":
            # monthly chart for selected year
            rows = db.execute(
                select(
                    extract("month", Payment.created_at),
                    func.coalesce(func.sum(Payment.total), 0),
                )
                .where(
                    Payment.status == "approved",
                    extract("year", Payment.created_at) == year,
                )
                .group_by(extract("month", Payment.created_at))
                .order_by(extract("month", Payment.created_at))
            ).all()
            sums_by_month = {int(m): float(s) for m, s in rows}

            chart_labels = [f"{months_th[m-1]} {year}" for m in range(1, 13)]
            chart_values = [sums_by_month.get(m, 0.0) for m in range(1, 13)]
            rev_period_total = sum(chart_values)

        else:  # rg == "all"
            # yearly chart for all data
            rows = db.execute(
                select(
                    extract("year", Payment.created_at),
                    func.coalesce(func.sum(Payment.total), 0),
                )
                .where(Payment.status == "approved")
                .group_by(extract("year", Payment.created_at))
                .order_by(extract("year", Payment.created_at))
            ).all()
            years_found = sorted({int(y) for y, _ in rows}) or [today.year]
            sums_by_year = {int(y): float(s) for y, s in rows}

            chart_labels = [str(y) for y in years_found]
            chart_values = [sums_by_year.get(y, 0.0) for y in years_found]
            rev_period_total = sum(chart_values)

        # ---------- latest lists ----------
        pending = (
            db.execute(
                select(Payment)
                .options(joinedload(Payment.user), joinedload(Payment.package))
                .where(Payment.status == "pending")
                .order_by(desc(Payment.updated_at), desc(Payment.id))
                .limit(10)
            ).scalars().all()
        )
        approved = (
            db.execute(
                select(Payment)
                .options(joinedload(Payment.user), joinedload(Payment.package))
                .where(Payment.status == "approved")
                .order_by(desc(Payment.updated_at), desc(Payment.id))
                .limit(10)
            ).scalars().all()
        )

        return render_template(
            "admin/dashboard.html",
            # stats
            stats={
                "total_users": total_users,
                "total_packages": total_packages,
                "total_promos": total_promos,
            },
            pending=pending,
            approved=approved,
            # filters (keep key 'range' intact)
            period=rg,
            year=year,
            month=month,
            years=years,
            months_th=months_th,
            months=list(range(1, 13)),  # for template
            # revenues
            rev_period_total=rev_period_total,
            rev_this_year=rev_this_year,
            rev_all_time=rev_all_time,
            # chart
            chart_labels=chart_labels,
            chart_values=chart_values,
        )
    finally:
        db.close()


@bp.get("/dashboard/pdf")
@_admin_required
def dashboard_pdf():
    """Generate a PDF summary of revenue for the selected period."""
    # ✅ import reportlab ตอนเรียกใช้ ไม่ import ตอนโหลดโมดูล
    from io import BytesIO
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    db = SessionLocal()
    try:
        today = date.today()
        rg = (request.args.get("range") or "monthly").lower()  # monthly | yearly | all
        year = int(request.args.get("year") or today.year)
        month = int(request.args.get("month") or today.month)

        months_th = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

        # ---------- base revenue summaries ----------
        rev_all_time = db.execute(
            select(func.coalesce(func.sum(Payment.total), 0))
            .where(Payment.status == "approved")
        ).scalar() or 0.0

        rev_this_year = db.execute(
            select(func.coalesce(func.sum(Payment.total), 0))
            .where(
                Payment.status == "approved",
                extract("year", Payment.created_at) == today.year,
            )
        ).scalar() or 0.0

        chart_labels: list[str] = []
        chart_values: list[float] = []
        rev_period_total = 0.0

        if rg == "monthly":
            last_day = monthrange(year, month)[1]
            rows = db.execute(
                select(
                    extract("day", Payment.created_at),
                    func.coalesce(func.sum(Payment.total), 0),
                )
                .where(
                    Payment.status == "approved",
                    extract("year", Payment.created_at) == year,
                    extract("month", Payment.created_at) == month,
                )
                .group_by(extract("day", Payment.created_at))
                .order_by(extract("day", Payment.created_at))
            ).all()
            sums_by_day = {int(d): float(s) for d, s in rows}

            chart_labels = [f"{d} {months_th[month-1]}" for d in range(1, last_day + 1)]
            chart_values = [sums_by_day.get(d, 0.0) for d in range(1, last_day + 1)]
            rev_period_total = sum(chart_values)

        elif rg == "yearly":
            rows = db.execute(
                select(
                    extract("month", Payment.created_at),
                    func.coalesce(func.sum(Payment.total), 0),
                )
                .where(
                    Payment.status == "approved",
                    extract("year", Payment.created_at) == year,
                )
                .group_by(extract("month", Payment.created_at))
                .order_by(extract("month", Payment.created_at))
            ).all()
            sums_by_month = {int(m): float(s) for m, s in rows}

            chart_labels = [f"{months_th[m-1]} {year}" for m in range(1, 13)]
            chart_values = [sums_by_month.get(m, 0.0) for m in range(1, 13)]
            rev_period_total = sum(chart_values)

        else:  # rg == "all"
            rows = db.execute(
                select(
                    extract("year", Payment.created_at),
                    func.coalesce(func.sum(Payment.total), 0),
                )
                .where(Payment.status == "approved")
                .group_by(extract("year", Payment.created_at))
                .order_by(extract("year", Payment.created_at))
            ).all()
            years_found = sorted({int(y) for y, _ in rows}) or [today.year]
            sums_by_year = {int(y): float(s) for y, s in rows}

            chart_labels = [str(y) for y in years_found]
            chart_values = [sums_by_year.get(y, 0.0) for y, s in rows]
            rev_period_total = sum(chart_values)

        # ---------- Build PDF ----------
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        width, height = A4
        y = height - 25 * mm

        # Title
        c.setFont("Helvetica-Bold", 16)
        c.drawString(20 * mm, y, "Revenue Summary")
        y -= 10 * mm

        # Meta info
        c.setFont("Helvetica", 10)
        if rg == "monthly":
            period_text = f"Range: Monthly   Year: {year}   Month: {months_th[month-1]}"
        elif rg == "yearly":
            period_text = f"Range: Yearly   Year: {year}"
        else:
            period_text = "Range: All years"
        c.drawString(20 * mm, y, period_text)
        y -= 6 * mm

        c.drawString(20 * mm, y, f"Generated at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        y -= 10 * mm

        # Summary numbers
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20 * mm, y, "Summary")
        y -= 7 * mm
        c.setFont("Helvetica", 10)
        c.drawString(25 * mm, y, f"Selected period total: {rev_period_total:,.2f} THB")
        y -= 6 * mm
        c.drawString(25 * mm, y, f"This year total:        {rev_this_year:,.2f} THB")
        y -= 6 * mm
        c.drawString(25 * mm, y, f"All time total:         {rev_all_time:,.2f} THB")
        y -= 10 * mm

        # Breakdown table
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20 * mm, y, "Breakdown")
        y -= 7 * mm
        c.setFont("Helvetica", 9)

        for label, value in zip(chart_labels, chart_values):
            if y < 20 * mm:
                c.showPage()
                y = height - 25 * mm
                c.setFont("Helvetica-Bold", 11)
                c.drawString(20 * mm, y, "Breakdown (cont.)")
                y -= 7 * mm
                c.setFont("Helvetica", 9)

            c.drawString(22 * mm, y, f"- {label}: {value:,.2f} THB")
            y -= 5 * mm

        c.showPage()
        c.save()
        buf.seek(0)

        if rg == "monthly":
            filename = f"revenue_{year}_{month:02d}.pdf"
        elif rg == "yearly":
            filename = f"revenue_{year}.pdf"
        else:
            filename = "revenue_all_years.pdf"

        return send_file(
            buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
        )
    finally:
        db.close()


# ------------------ Payments ------------------
@bp.get("/payments")
@_admin_required
def payments():
    q = (request.args.get("q") or "").strip().lower()
    status = request.args.get("status") or "all"
    sort = request.args.get("sort") or "updated_desc"

    db = SessionLocal()
    try:
        stmt = (
            select(Payment)
            .options(joinedload(Payment.user), joinedload(Payment.package), joinedload(Payment.promotion))
        )
        if status != "all":
            stmt = stmt.where(Payment.status == status)

        sort_map = {
            "updated_desc": (Payment.updated_at, True),
            "updated_asc": (Payment.updated_at, False),
            "id_desc": (Payment.id, True),
            "id_asc": (Payment.id, False),
            "total_desc": (Payment.total, True),
            "total_asc": (Payment.total, False),
        }
        col, desc_flag = sort_map.get(sort, (Payment.updated_at, True))
        stmt = stmt.order_by(desc(col), desc(Payment.id)) if desc_flag else stmt.order_by(col, Payment.id)

        rows = db.execute(stmt).scalars().all()

        if q:
            def _match(p: Payment) -> bool:
                uname = (p.user.username if p.user else "") or ""
                pkg = ((p.package.name or "") + " " + (p.package.code or "")) if p.package else ""
                promo = ((p.promotion.name or "") + " " + (p.promotion.code or "")) if p.promotion else ""
                return q in uname.lower() or q in pkg.lower() or q in promo.lower()
            rows = [r for r in rows if _match(r)]

        return render_template("admin/payments.html", rows=rows, q=q, status=status, sort=sort)
    finally:
        db.close()


@bp.get("/payments/<int:pid>")
@_admin_required
def payment_detail(pid: int):
    db = SessionLocal()
    try:
        p = db.execute(
            select(Payment)
            .options(joinedload(Payment.user), joinedload(Payment.package), joinedload(Payment.promotion))
            .where(Payment.id == pid)
        ).scalar_one_or_none()
        if not p:
            flash("Payment not found.", "error")
            return redirect(url_for("admin.payments"))
        return render_template("admin/payment_detail.html", p=p)
    finally:
        db.close()


def _grant_package_to_user(db, pay: Payment) -> None:
    """
    Grant credits/package duration to a user after a payment gets approved.
    Call this only when status changes from non-approved -> approved.
    """
    pkg = db.get(Package, pay.package_id)
    if not pkg:
        raise RuntimeError("Package for this payment was not found.")

    # duration
    end_at = None if pkg.is_lifetime else (datetime.utcnow() + timedelta(days=int(pkg.duration_days or 0)))

    up = UserPackage(
        user_id=pay.user_id,
        package_id=pkg.id,
        remaining_calls=int(pkg.credits or 0),
        end_at=end_at,
        status="active",
    )
    db.add(up)


@bp.post("/payments/<int:pid>/approve")
@_admin_required
def payment_approve(pid: int):
    db = SessionLocal()
    try:
        p = db.get(Payment, pid)
        if not p:
            flash("Payment not found.", "error")
            return redirect(url_for("admin.payments", **request.args))

        # idempotency: grant only if not already approved
        if p.status != "approved":
            _grant_package_to_user(db, p)
            p.status = "approved"
            p.verified_at = datetime.utcnow()
            p.verified_by = int(getattr(current_user, "id"))
            p.updated_at = datetime.utcnow()
            db.add(p)
            db.commit()
            flash("Approved and credits granted to the user.", "success")
        else:
            flash("This payment is already approved (no duplicate grant).", "info")

        return redirect(url_for("admin.payment_detail", pid=p.id))
    except Exception as e:
        db.rollback()
        flash(f"Approval failed: {e}", "error")
        return redirect(url_for("admin.payments", **request.args))
    finally:
        db.close()


@bp.post("/payments/<int:pid>/reject")
@_admin_required
def payment_reject(pid: int):
    db = SessionLocal()
    try:
        p = db.get(Payment, pid)
        if not p:
            flash("Payment not found.", "error")
            return redirect(url_for("admin.payments", **request.args))
        p.status = "rejected"
        p.updated_at = datetime.utcnow()
        db.add(p)
        db.commit()
        flash("Rejected successfully.", "success")
        return redirect(url_for("admin.payment_detail", pid=pid))
    finally:
        db.close()


@bp.get("/payments/<int:pid>/slip")
@_admin_required
def payment_slip(pid: int):
    db = SessionLocal()
    try:
        p = db.get(Payment, pid)
        if not p or not p.slip_url:
            flash("Slip not found.", "error")
            return redirect(url_for("admin.payment_detail", pid=pid))

        path = p.slip_url
        if not os.path.isabs(path):
            path = os.path.normpath(os.path.join(os.getcwd(), path))

        if not os.path.exists(path):
            flash("Slip file not found on disk.", "error")
            return redirect(url_for("admin.payment_detail", pid=pid))

        return send_file(path)
    finally:
        db.close()


# ------------------ Packages ------------------
@bp.get("/packages")
@_admin_required
def packages():
    sort = request.args.get("sort") or "id_desc"
    lifetime = request.args.get("lifetime") or "all"

    db = SessionLocal()
    try:
        _auto_expire_promotions(db)
        stmt = select(Package).options(joinedload(Package.promotion))
        if lifetime == "yes":
            stmt = stmt.where(Package.is_lifetime.is_(True))
        elif lifetime == "no":
            stmt = stmt.where(Package.is_lifetime.is_(False))

        sort_map = {
            "price_asc": (Package.price_thb, False),
            "price_desc": (Package.price_thb, True),
            "credits_asc": (Package.credits, False),
            "credits_desc": (Package.credits, True),
            "created_desc": (Package.created_at, True),
            "created_asc": (Package.created_at, False),
            "id_desc": (Package.id, True),
            "id_asc": (Package.id, False),
        }
        col, desc_flag = sort_map.get(sort, (Package.id, True))
        stmt = stmt.order_by(desc(col), desc(Package.id)) if desc_flag else stmt.order_by(col, Package.id)

        rows = db.execute(stmt).scalars().all()

        promos = (
            db.execute(
                select(Promotion)
                .where(Promotion.status == "active")
                .order_by(desc(Promotion.updated_at), Promotion.id)
            ).scalars().all()
        )

        return render_template("admin/packages.html", packages=rows, promotions=promos, sort=sort, lifetime=lifetime)
    finally:
        db.close()


@bp.post("/packages/create")
@_admin_required
def packages_create():
    f = request.form
    db = SessionLocal()
    try:
        pkg = Package(
            code=f["code"].strip(),
            name=f["name"].strip(),
            price_thb=(f.get("price_thb") or "0").replace(",", ""),
            credits=int(f.get("credits") or 0),
            duration_days=(int(f.get("duration_days") or 0) or None),
            is_lifetime=True if f.get("is_lifetime") else False,
            status=f.get("status") or "active",
            promotion_id=(int(f["promotion_id"]) if f.get("promotion_id") else None),
        )
        db.add(pkg)
        db.commit()
        flash("Package created.", "success")
        return redirect(url_for("admin.packages"))
    except Exception as e:
        db.rollback()
        flash(f"Failed to create package: {e}", "error")
        return redirect(url_for("admin.packages"))
    finally:
        db.close()


@bp.post("/packages/update/<int:pkg_id>")
@_admin_required
def packages_update(pkg_id: int):
    f = request.form
    db = SessionLocal()
    try:
        p = db.get(Package, pkg_id)
        if not p:
            flash("Package not found.", "error")
            return redirect(url_for("admin.packages"))

        p.code = f.get("code", p.code).strip()
        p.name = f.get("name", p.name).strip()
        price_raw = f.get("price_thb") or p.price_thb
        if isinstance(price_raw, str):
            p.price_thb = price_raw.replace(",", "")
        else:
            p.price_thb = price_raw
        p.credits = int(f.get("credits") or p.credits or 0)
        dur = f.get("duration_days")
        p.duration_days = int(dur) if dur not in (None, "",) else None
        p.is_lifetime = True if f.get("is_lifetime") else False
        p.status = f.get("status", p.status)
        p.promotion_id = int(f["promotion_id"]) if f.get("promotion_id") else None
        p.updated_at = datetime.utcnow()

        db.add(p)
        db.commit()
        flash("Package updated.", "success")
        return redirect(url_for("admin.packages", **request.args))
    except Exception as e:
        db.rollback()
        flash(f"Update failed: {e}", "error")
        return redirect(url_for("admin.packages", **request.args))
    finally:
        db.close()


# ------------------ Promotions ------------------
@bp.get("/promotions")
@_admin_required
def promotions():
    q = (request.args.get("q") or "").strip().lower()
    status = request.args.get("status") or "all"
    sort = request.args.get("sort") or "created_desc"

    db = SessionLocal()
    try:
        stmt = select(Promotion)
        if status != "all":
            stmt = stmt.where(Promotion.status == status)

        sort_map = {
            "created_desc": (Promotion.created_at, True),
            "created_asc": (Promotion.created_at, False),
            "updated_desc": (Promotion.updated_at, True),
            "updated_asc": (Promotion.updated_at, False),
            "id_desc": (Promotion.id, True),
            "id_asc": (Promotion.id, False),
        }
        col, desc_flag = sort_map.get(sort, (Promotion.id, True))
        stmt = stmt.order_by(desc(col), desc(Promotion.id)) if desc_flag else stmt.order_by(col, Promotion.id)

        rows = db.execute(stmt).scalars().all()
        if q:
            rows = [r for r in rows if q in r.code.lower() or q in r.name.lower()]

        return render_template("admin/promotions.html", rows=rows, q=q, status=status, sort=sort)
    finally:
        db.close()


@bp.post("/promotions/create")
@_admin_required
def promotions_create():
    f = request.form
    db = SessionLocal()
    try:
        promo = Promotion(
            code=f["code"].strip(),
            name=f["name"].strip(),
            discount_percent=int(f.get("discount_percent") or 0),
            start_date=(f.get("start_date") or None),
            end_date=(f.get("end_date") or None),
            status=f.get("status") or "active",
        )
        db.add(promo)
        db.commit()
        flash("Promotion created.", "success")
        return redirect(url_for("admin.promotions", **request.args))
    except Exception as e:
        db.rollback()
        flash(f"Failed to create promotion: {e}", "error")
        return redirect(url_for("admin.promotions", **request.args))
    finally:
        db.close()


@bp.post("/promotions/update/<int:pid>")
@_admin_required
def promotions_update(pid: int):
    f = request.form
    db = SessionLocal()
    try:
        p = db.get(Promotion, pid)
        if not p:
            flash("Promotion not found.", "error")
            return redirect(url_for("admin.promotions"))
        p.code = f.get("code", p.code).strip()
        p.name = f.get("name", p.name).strip()
        p.discount_percent = int(f.get("discount_percent") or p.discount_percent or 0)
        p.start_date = f.get("start_date") or None
        p.end_date = f.get("end_date") or None
        p.status = f.get("status", p.status)
        p.updated_at = datetime.utcnow()
        db.add(p)
        db.commit()
        flash("Promotion updated.", "success")
        return redirect(url_for("admin.promotions", **request.args))
    except Exception as e:
        db.rollback()
        flash(f"Update failed: {e}", "error")
        return redirect(url_for("admin.promotions", **request.args))
    finally:
        db.close()


# ------------------ Users ------------------
@bp.get("/users")
@_admin_required
def users():
    q = (request.args.get("q") or "").strip().lower()
    status = request.args.get("status") or "all"
    admin = request.args.get("admin") or "all"
    sort = request.args.get("sort") or "id_desc"

    db = SessionLocal()
    try:
        stmt = select(User)
        if status != "all":
            stmt = stmt.where(User.status == status)
        if admin != "all":
            stmt = stmt.where(User.is_admin == (admin == "yes"))

        sort_map = {
            "id_desc": (User.id, True),
            "id_asc": (User.id, False),
            "name_asc": (User.username, False),
            "name_desc": (User.username, True),
        }
        col, desc_flag = sort_map.get(sort, (User.id, True))
        stmt = stmt.order_by(desc(col)) if desc_flag else stmt.order_by(col)

        rows = db.execute(stmt).scalars().all()
        if q:
            rows = [u for u in rows if q in u.username.lower()]

        return render_template("admin/users.html", rows=rows, q=q, status=status, admin=admin, sort=sort)
    finally:
        db.close()


@bp.post("/users/<int:uid>/toggle")
@_admin_required
def users_toggle(uid: int):
    db = SessionLocal()
    try:
        u = db.get(User, uid)
        if not u:
            flash("User not found.", "error")
            return redirect(url_for("admin.users"))
        u.status = "inactive" if u.status == "active" else "active"
        u.updated_at = datetime.utcnow()
        db.add(u)
        db.commit()
        flash("User status toggled.", "success")
        return redirect(url_for("admin.users", **request.args))
    finally:
        db.close()


@bp.post("/users/<int:uid>/toggle-admin")
@_admin_required
def users_toggle_admin(uid: int):
    db = SessionLocal()
    try:
        u = db.get(User, uid)
        if not u:
            flash("User not found.", "error")
            return redirect(url_for("admin.users"))
        u.is_admin = not u.is_admin
        u.updated_at = datetime.utcnow()
        db.add(u)
        db.commit()
        flash("Admin status toggled.", "success")
        return redirect(url_for("admin.users", **request.args))
    finally:
        db.close()
