# app/routes/shop.py
# -*- coding: utf-8 -*-
import os, sys, uuid, json, re
from datetime import timedelta, datetime, date
from typing import List, Optional

from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import joinedload

from app.db import SessionLocal
from app.models import (
    Package, Payment, UserPackage,
    CarCache, SearchSession, SearchSessionCar, Promotion
)
from app.services.credits import consume_one_credit
from app.services.llm_select import pick_best_car_with_gemini

bp = Blueprint("shop", __name__, template_folder="../templates/shop")


def _auto_expire_promotions(db):
    """Auto-close active promotions with end_date in the past (same rule as admin side)."""
    today = datetime.utcnow().date()
    rows = db.execute(select(Promotion).where(Promotion.status == "active")).scalars().all()
    changed = 0
    for p in rows:
        ed = _parse_date(getattr(p, "end_date", None))
        if ed and today > ed and p.status == "active":
            p.status = "inactive"
            p.updated_at = datetime.utcnow()
            db.add(p)
            changed += 1
    if changed:
        db.commit()


# ----------------------------- utils -----------------------------
def allowed_file(filename: str) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in current_app.config.get("ALLOWED_EXTENSIONS", {"jpg", "jpeg", "png", "pdf"})

def _to_int(s: str | None) -> int | None:
    if s is None:
        return None
    m = re.findall(r"\d+", str(s))
    if not m:
        return None
    try:
        return int("".join(m))
    except Exception:
        return None

def _available_credits(db, user_id: int) -> int:
    stmt = (
        select(func.coalesce(func.sum(UserPackage.remaining_calls), 0))
        .where(
            UserPackage.user_id == user_id,
            UserPackage.status == "active",
            or_(UserPackage.end_at.is_(None), UserPackage.end_at > func.now()),
        )
    )
    return int(db.execute(stmt).scalar() or 0)

def _purge_cache_for_source(db, source: str) -> int:
    # Support both columns source and source_site
    car_ids = db.execute(
        select(CarCache.id).where(or_(CarCache.source == source, CarCache.source_site == source))
    ).scalars().all()
    if car_ids:
        db.query(SearchSessionCar).filter(SearchSessionCar.car_id.in_(car_ids)).delete(synchronize_session=False)
        db.flush()
    deleted = db.query(CarCache).filter(or_(CarCache.source == source, CarCache.source_site == source)) \
        .delete(synchronize_session=False)
    return deleted

def _run_scraper(source: str, q: str, min_price: int, max_price: int, limit: int) -> tuple[bool, str]:
    import subprocess
    py = sys.executable

    chromedriver = current_app.config.get("SCRAPER_CHROMEDRIVER", "") or os.getenv("CHROMEDRIVER_PATH", "")
    headless = current_app.config.get("SCRAPER_HEADLESS", True)
    debug_dump = current_app.config.get("SCRAPER_DEBUG_DUMP", False)

    if source == "kaidee":
        script = os.path.join(os.getcwd(), "scripts", "scrape_kaidee.py")
    elif source == "carsome":
        script = os.path.join(os.getcwd(), "scripts", "scrape_carsome.py")
    elif source == "one2car":
        script = os.path.join(os.getcwd(), "scripts", "scrape_one2car.py")
    elif source == "roddonjai":
        script = os.path.join(os.getcwd(), "scripts", "scrape_roddonjai.py")
    else:
        return False, f"unknown source: {source}"

    args = [
        py, script,
        "--q", q or "",
        "--min", str(min_price),
        "--max", str(max_price),
        "--limit", str(limit),
    ]
    if chromedriver:
        args += ["--chromedriver", chromedriver]
    if headless:
        args.append("--headless")
    if debug_dump:
        args.append("--debug-dump")

    # เพิ่ม debug พิเศษให้ roddonjai
    if source == "roddonjai":
        args.append("--debug-fuel")

    print(f"DEBUG run {source} args: {args}")

    try:
        timeout_sec = int(current_app.config.get("SCRAPER_TIMEOUT_SEC", 480))
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout_sec)
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        ok = proc.returncode == 0
        if not ok:
            # log error ของ source นั้น ๆ ด้วย ถึงแม้ source อื่นจะ ok
            print(f"[{source}] ERROR exit={proc.returncode}")
            if stdout:
                print(f"[{source}] STDOUT (error case):\n{stdout}")
            if stderr:
                print(f"[{source}] STDERR:\n{stderr}")
            return False, f"[{source}] exit={proc.returncode}\n{stdout}\n{stderr}"
        if stdout:
            print(f"[{source}] STDOUT:\n{stdout}")
        if stderr:
            print(f"[{source}] STDERR:\n{stderr}")
        return True, stdout[-2000:]
    except Exception as e:
        print(f"[{source}] EXCEPTION in _run_scraper: {e}")
        return False, f"[{source}] exception: {e}"

def _extract_year_from_text(x) -> Optional[int]:
    """Extract a 4-digit year from text, e.g., 'year 2018 (registered 2019)' => 2018."""
    if x is None:
        return None
    m = re.search(r"(20\d{2}|19\d{2})", str(x))
    return int(m.group(1)) if m else None

def _get_car_year(c: CarCache) -> Optional[int]:
    """Return year from main column or from various keys in 'extra'."""
    if getattr(c, "year", None) is not None:
        try:
            return int(c.year)
        except Exception:
            pass
    ex = c.extra or {}
    sp = ex.get("สเปกย่อย") or {}
    # Try common keys
    for k in ("ปีรถ", "ปี", "year", "ปีผลิต"):
        y = ex.get(k)
        yy = _extract_year_from_text(y)
        if yy:
            return yy
    for k in ("ปีจดทะเบียน",):
        y = sp.get(k)
        yy = _extract_year_from_text(y)
        if yy:
            return yy
    return None

def _match_extra_filters(
    c: CarCache,
    car_type: str,
    fuel_type: str,
    gear_type: str,
    color: str,
    min_year: Optional[int],
    max_year: Optional[int],
) -> bool:
    extra = c.extra or {}
    def norm(x: str | None) -> str:
        return (x or "").strip().lower()

    # --- body type ---
    if car_type:
        ct = norm(car_type)
        val = (
            norm(extra.get("ประเภทรถ")) or
            norm(extra.get("ตัวถัง")) or
            norm(extra.get("ประเภทตัวถัง")) or
            norm((extra.get("สเปกย่อย") or {}).get("ประเภทรถ")) or
            norm(extra.get("body_type"))
        )
        if ct and val and ct not in val:
            return False

    # --- fuel ---
    if fuel_type:
        ft = norm(fuel_type)
        val = (
            norm(extra.get("เชื้อเพลิง")) or
            norm(extra.get("น้ำมัน")) or
            norm((extra.get("สเปกย่อย") or {}).get("เชื้อเพลิง")) or
            norm((extra.get("สเปกย่อย") or {}).get("น้ำมัน"))
        )
        if ft and val and ft not in val:
            return False

    # --- transmission ---
    if gear_type:
        gt = norm(gear_type)
        val = (
            norm(extra.get("เกียร์")) or
            norm(extra.get("ระบบเกียร์")) or
            norm((extra.get("สเปกย่อย") or {}).get("เกียร์"))
        )
        if gt and val and gt not in val:
            return False

    # --- color ---
    if color:
        cc = norm(color)
        val = norm(extra.get("สี")) or norm((extra.get("สเปกย่อย") or {}).get("สี"))
        if cc and val and cc not in val:
            return False

    # --- year range ---
    if min_year or max_year:
        y = _get_car_year(c)
        # If user set a year range but the listing has no year -> exclude
        if y is None:
            return False
        if min_year and y < min_year:
            return False
        if max_year and y > max_year:
            return False

    return True

# ---------- promo helpers ----------
def _parse_date(s: Optional[str]) -> Optional[date]:
    """Try to parse multiple date formats and return a naive date object."""
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None

def _is_promo_active(p: Promotion) -> bool:
    if not p:
        return False
    if (p.status or "").lower() != "active":
        return False
    today = datetime.utcnow().date()
    start_ok = True
    end_ok = True
    sd = _parse_date(getattr(p, "start_date", None))
    ed = _parse_date(getattr(p, "end_date", None))
    if sd:
        start_ok = today >= sd
    if ed:
        end_ok = today <= ed
    return start_ok and end_ok

def _effective_price(pkg: Package) -> float:
    """Compute effective price after promotion (if active)."""
    base = float(pkg.price_thb or 0)
    promo = getattr(pkg, "promotion", None)
    if promo and _is_promo_active(promo):
        pct = int(promo.discount_percent or 0)
        if pct > 0:
            eff = round(base * (100 - pct) / 100.0, 2)
            if eff < 0:
                eff = 0.0
            return eff
    return base

def _has_used_trial(db, user_id: int) -> bool:
    """
    Define Trial = any package with base price == 0 (not relying on promo 100%).
    A user can use Trial only once in total (across all trial packages).
    """
    q = (
        select(UserPackage.id)
        .join(Package, Package.id == UserPackage.package_id)
        .where(UserPackage.user_id == user_id, func.coalesce(Package.price_thb, 0) <= 0)
        .limit(1)
    )
    return db.execute(q).scalar_one_or_none() is not None

# ---------- sort helpers ----------
def _safe_int(x, default_big=True):
    try:
        return int(x)
    except Exception:
        return 10**15 if default_big else -10**15

def _safe_str(x):
    return (x or "").strip().lower()

def _apply_sort(cars, sort_key: str):
    if not sort_key: return cars
    key = sort_key.lower()

    if key == "price_asc":
        return sorted(cars, key=lambda c: _safe_int(getattr(c, "price_thb", None)))
    if key == "price_desc":
        return sorted(cars, key=lambda c: _safe_int(getattr(c, "price_thb", None)), reverse=True)

    if key == "year_asc":
        return sorted(cars, key=lambda c: _safe_int(getattr(c, "year", None)))
    if key == "year_desc":
        return sorted(cars, key=lambda c: _safe_int(getattr(c, "year", None)), reverse=True)

    if key == "mileage_asc":
        return sorted(cars, key=lambda c: _safe_int(getattr(c, "mileage_km", None)))
    if key == "mileage_desc":
        return sorted(cars, key=lambda c: _safe_int(getattr(c, "mileage_km", None)), reverse=True)

    if key == "brand_az":
        return sorted(cars, key=lambda c: _safe_str(getattr(c, "brand", None)))
    if key == "brand_za":
        return sorted(cars, key=lambda c: _safe_str(getattr(c, "brand", None)), reverse=True)

    if key == "source":
        return sorted(cars, key=lambda c: _safe_str(getattr(c, "source", None) or getattr(c, "source_site", None)))

    return cars

# ----------------------------- Search -----------------------------
@bp.get("/search")
@login_required
def search():
    db = SessionLocal()
    try:
        credits = _available_credits(db, current_user.id)
        trial_used = _has_used_trial(db, current_user.id)
        has_active_package = credits > 0
    finally:
        db.close()
    return render_template(
        "shop/search.html",
        trial_used=trial_used,
        has_active_package=has_active_package,
        available_credits=credits,
    )

# Method B: loading page
@bp.post("/search/loading")
@login_required
def search_loading():
    form_data = request.form.to_dict(flat=True)
    return render_template("shop/search_loading.html", form=form_data)

@bp.post("/search/start")
@login_required
def search_start():
    from collections import Counter

    q = (request.form.get("q") or "").strip()

    # ---- total items user wants to fetch (20/30/40/50) ----
    total_limit_raw = (request.form.get("total_limit") or "").strip()
    total_limit = _to_int(total_limit_raw) or 20
    if total_limit not in (20, 30, 40, 50):
        flash("Invalid selection (allowed: 20, 30, 40, 50).", "error")
        return redirect(url_for("shop.search"))

    # ---- use budget 'max' ----
    max_budget_raw = (request.form.get("max_budget") or "").strip()
    max_budget = _to_int(max_budget_raw)
    if max_budget is None or max_budget <= 0:
        flash("Please provide a valid max budget (number).", "error")
        return redirect(url_for("shop.search"))

    # extra fields
    salary = (request.form.get("salary") or "").strip()
    gender = (request.form.get("gender") or "").strip()
    marital_status = (request.form.get("marital_status") or "").strip()
    occupation = (request.form.get("occupation") or "").strip()
    education_level = (request.form.get("education_level") or "").strip()

    car_type = (request.form.get("car_type") or "").strip()
    fuel_type = (request.form.get("fuel_type") or "").strip()
    gear_type = (request.form.get("gear_type") or "").strip()
    color = (request.form.get("color") or "").strip()

    # ✅ year range
    min_year = _to_int((request.form.get("min_year") or "").strip())
    max_year = _to_int((request.form.get("max_year") or "").strip())
    if min_year and (min_year < 1900 or min_year > 2100):
        flash("Invalid year (from).", "error"); return redirect(url_for("shop.search"))
    if max_year and (max_year < 1900 or max_year > 2100):
        flash("Invalid year (to).", "error"); return redirect(url_for("shop.search"))
    if min_year and max_year and max_year < min_year:
        # swap automatically for convenience
        min_year, max_year = max_year, min_year

    purpose = (request.form.get("purpose") or "").strip()
    other_prefs = (request.form.get("other_prefs") or "").strip()

    db = SessionLocal()
    try:
        if _available_credits(db, current_user.id) <= 0:
            flash("Insufficient credits. Please purchase a package.", "error")
            return redirect(url_for("shop.list_packages"))

        # include roddonjai by default as well (no one2car)
        sources_cfg = current_app.config.get("SCRAPER_SOURCES", "kaidee,carsome,roddonjai")
        sources = [s.strip() for s in sources_cfg.split(",") if s.strip()]

        # บังคับตัด one2car ทิ้ง เผื่อมีใน config/.env
        sources = [s for s in sources if s.lower() != "one2car"]

        if not sources:
            # เผื่อ config พลาด
            sources = ["kaidee", "carsome", "roddonjai"]

        print("DEBUG SCRAPER_SOURCES (final) =", sources, "Q =", q)

        # clear cache per source
        for s in sources:
            purged = _purge_cache_for_source(db, s)
            print(f"DEBUG purged {purged} rows for source={s}")
        db.commit()

        # spread target count across sources
        n_sources = max(1, len(sources))
        per_source_limit = (total_limit + n_sources - 1) // n_sources  # ceil
        cfg_cap = int(current_app.config.get("SCRAPER_LIMIT_PER_SOURCE",
                                             current_app.config.get("SCRAPER_LIMIT", per_source_limit)))
        if cfg_cap > 0:
            per_source_limit = min(per_source_limit, cfg_cap)

        display_limit = total_limit

        any_ok = False
        last_msg = ""
        for s in sources:
            ok, msg = _run_scraper(s, q=q, min_price=0, max_price=max_budget, limit=per_source_limit)
            last_msg = msg
            if ok:
                any_ok = True

        if not any_ok:
            flash("An error occurred while fetching data from external sources.", "error")
            if last_msg:
                print(last_msg)
            return redirect(url_for("shop.search"))

        # ---- filter by budget 'max' ----
        conds = [CarCache.price_thb.isnot(None), CarCache.price_thb <= max_budget]
        if q:
            like = f"%{q}%"
            conds.append(or_(CarCache.title.ilike(like), CarCache.brand.ilike(like), CarCache.model.ilike(like)))
        if sources:
            conds.append(or_(CarCache.source.in_(sources), CarCache.source_site.in_(sources)))

        rows = db.execute(
            select(CarCache).where(and_(*conds)).order_by(CarCache.price_thb.asc()).limit(display_limit * 3)
        ).scalars().all()

        rows_by_source = Counter((getattr(c, "source", None) or getattr(c, "source_site", None) or "NONE") for c in rows)
        print("DEBUG rows_from_db=%d" % len(rows))
        print("DEBUG rows_by_source:", rows_by_source)

        # ✅ apply year range with other filters
        cars = [
            c for c in rows
            if _match_extra_filters(c, car_type, fuel_type, gear_type, color, min_year, max_year)
        ]

        cars_by_source = Counter((getattr(c, "source", None) or getattr(c, "source_site", None) or "NONE") for c in cars)
        print("DEBUG after_extra_filters=%d" % len(cars))
        print("DEBUG cars_by_source:", cars_by_source)

        if not cars:
            flash("No results found for the given filters.", "info")
            return redirect(url_for("shop.search"))

        # consume credit only after we have results
        if not consume_one_credit(db, current_user.id):
            flash("Insufficient credits. Please purchase a package.", "error")
            return redirect(url_for("shop.list_packages"))

        params = {
            "q": q,
            "max_budget": max_budget,
            "salary": salary,
            "gender": gender,
            "marital_status": marital_status,
            "occupation": occupation,
            "education_level": education_level,
            "car_type": car_type,
            "fuel_type": fuel_type,
            "gear_type": gear_type,
            "color": color,
            "min_year": min_year,   # ✅ store into session
            "max_year": max_year,   # ✅ store into session
            "purpose": purpose,
            "other_prefs": other_prefs,
            "sources": sources,
            "total_limit": total_limit,
            "per_source_limit": per_source_limit
        }
        ss = SearchSession(user_id=current_user.id, params_json=params, status="done")
        db.add(ss)
        db.flush()

        cars = cars[:display_limit]
        for idx, c in enumerate(cars, start=1):
            db.add(SearchSessionCar(session_id=ss.id, car_id=c.id, rank=idx))

        db.commit()
        return redirect(url_for("shop.search_view", session_id=ss.id))

    except Exception as e:
        db.rollback()
        print("search_start error:", e)
        flash("An error occurred while fetching data from external sources.", "error")
        return redirect(url_for("shop.search"))
    finally:
        db.close()

@bp.get("/search/<int:session_id>")
@login_required
def search_view(session_id: int):
    from collections import Counter

    sort = request.args.get("sort", "").strip()

    db = SessionLocal()
    try:
        ss = db.get(SearchSession, session_id)
        if not ss or ss.user_id != current_user.id:
            flash("Search session not found.", "error")
            return redirect(url_for("shop.search"))

        rows = db.execute(
            select(SearchSessionCar)
            .where(SearchSessionCar.session_id == ss.id)
            .order_by(SearchSessionCar.rank)
        ).scalars().all()
        cars = [r.car for r in rows]
        by_source = Counter((getattr(c, "source", None) or getattr(c, "source_site", None) or "NONE") for c in cars)
        print("DEBUG search_view sources:", by_source)

        cars = _apply_sort(cars, sort)
        return render_template("shop/search_results.html", session=ss, cars=cars, sort=sort)
    finally:
        db.close()

@bp.get("/search/<int:session_id>/best")
@login_required
def best_car(session_id: int):
    db = SessionLocal()
    try:
        ss = db.get(SearchSession, session_id)
        if not ss or ss.user_id != current_user.id:
            flash("No suitable recommendation found.", "error")
            return redirect(url_for("shop.search"))

        rows = db.execute(
            select(SearchSessionCar)
            .where(SearchSessionCar.session_id == ss.id)
            .order_by(SearchSessionCar.rank)
        ).scalars().all()
        cars = [r.car for r in rows]

        raw = ss.params_json
        params = raw if isinstance(raw, dict) else (json.loads(raw or "{}") if raw else {})

        excl_raw = (request.args.get("exclude") or "").strip()
        exclude_ids: List[int] = []
        if excl_raw:
            for p in excl_raw.split(","):
                p = p.strip()
                if p:
                    try:
                        exclude_ids.append(int(p))
                    except:
                        pass

        best, reason = pick_best_car_with_gemini(
            cars=cars,
            session_params=params,
            exclude_ids=exclude_ids,
            fallback_first=True
        )

        if not best:
            flash("No suitable recommendation found.", "info")
            return redirect(url_for("shop.search_view", session_id=ss.id))

        others = [c for c in cars if c.id != best.id and c.id not in exclude_ids]
        others = sorted(others, key=lambda c: (c.price_thb is None, c.price_thb))[:8]

        next_exclude = ",".join([*(str(i) for i in exclude_ids), str(best.id)]) if exclude_ids else str(best.id)

        return render_template(
            "shop/best_car.html",
            session=ss,
            car=best,
            reason=reason,
            next_exclude=next_exclude,
            others=others
        )
    finally:
        db.close()

# ----------------------- Packages / Payment -----------------------
@bp.get("/packages")
@login_required
def list_packages():
    db = SessionLocal()
    try:
        _auto_expire_promotions(db)
        rows = db.execute(
            select(Package)
            .where(Package.status == "active")
            .options(joinedload(Package.promotion))   # ✅ eager-load promotion
            .order_by(Package.id)
        ).scalars().all()

        # has this user already used any Free Trial (count every trial)
        trial_used = _has_used_trial(db, current_user.id)

        # ✅ compute effective price and attach helper fields for template
        for pkg in rows:
            base = float(pkg.price_thb or 0)
            eff = _effective_price(pkg)                   # apply promo + date range rules
            promo_active = _is_promo_active(getattr(pkg, "promotion", None))
            setattr(pkg, "_base", base)
            setattr(pkg, "_eff", eff)
            setattr(pkg, "_promo_active", promo_active)

        return render_template("shop/packages.html", packages=rows, trial_used=trial_used)
    finally:
        db.close()

@bp.post("/packages/<int:pkg_id>/activate_free")
@login_required
def activate_free(pkg_id: int):
    db = SessionLocal()
    try:
        pkg = db.get(Package, pkg_id)
        if not pkg or pkg.status != "active":
            flash("Package not found.", "error")
            return redirect(url_for("shop.list_packages"))

        # Free Trial = base price == 0 only (not via promo)
        if float(pkg.price_thb or 0) > 0:
            flash("This package is not a free package.", "error")
            return redirect(url_for("shop.list_packages"))

        # prevent using trial more than once across trials
        if _has_used_trial(db, current_user.id):
            flash("You have already used your trial.", "info")
            return redirect(url_for("shop.list_packages"))

        # no admin approval: grant immediately
        now = datetime.utcnow()
        end_at = None if pkg.is_lifetime else now + timedelta(days=int(pkg.duration_days or 0))

        up = UserPackage(
            user_id=current_user.id,
            package_id=pkg.id,
            remaining_calls=int(pkg.credits or 0),
            end_at=end_at,
            status="active"
        )
        db.add(up)
        db.commit()
        flash(f"Free package activated! You received {pkg.credits} credits.", "success")
        return redirect(url_for("auth.dashboard"))
    finally:
        db.close()

@bp.post("/packages/<int:pkg_id>/buy")
@login_required
def buy_package(pkg_id: int):
    db = SessionLocal()
    try:
        pkg = db.get(Package, pkg_id)
        if not pkg or pkg.status != "active":
            flash("Package not found.", "error")
            return redirect(url_for("shop.list_packages"))

        # compute 'effective' price for billing
        base = float(pkg.price_thb or 0)
        eff = _effective_price(pkg)  # 👉 ราคาแพ็กเกจที่ผู้ใช้เห็น (รวม VAT แล้ว)
        promo_id_to_set = pkg.promotion_id if eff < base else None

        # 👉 ตีความ eff ว่า "ราคาพร้อม VAT 7%" แล้ว
        total = round(float(eff), 2)        # เช่น 35.00
        amount_net = round(total / 1.07, 2) # ราคาก่อน VAT (3x.xx)
        vat = round(total - amount_net, 2)  # ส่วนของ VAT 7%

        # กันกรณีปัดเศษแล้วไม่เป๊ะ
        if round(amount_net + vat, 2) != total:
            vat = round(total - amount_net, 2)

        amount = amount_net

        # ✅ set initial status to draft (user will upload slip before sending to admin)
        pay = Payment(
            user_id=current_user.id,
            package_id=pkg.id,
            promotion_id=promo_id_to_set,  # record which promo was applied
            amount=amount, vat=vat, total=total,
            method="qr", status="draft"
        )
        db.add(pay)
        db.commit()
        return redirect(url_for("shop.payment_upload", payment_id=pay.id))
    finally:
        db.close()

@bp.get("/payments/<int:payment_id>")
@login_required
def payment_upload(payment_id: int):
    db = SessionLocal()
    try:
        pay = db.get(Payment, payment_id)
        if not pay or pay.user_id != current_user.id:
            flash("Payment not found.", "error")
            return redirect(url_for("shop.list_packages"))
        pkg = db.get(Package, pay.package_id)
        return render_template("shop/payment_upload.html", payment=pay, package=pkg)
    finally:
        db.close()

@bp.post("/payments/<int:payment_id>/upload")
@login_required
def payment_upload_post(payment_id: int):
    file = request.files.get("slip")
    if not file or file.filename == "":
        flash("Please select a slip file.", "error")
        return redirect(url_for("shop.payment_upload", payment_id=payment_id))

    if not allowed_file(file.filename):
        flash("File type not allowed.", "error")
        return redirect(url_for("shop.payment_upload", payment_id=payment_id))

    db = SessionLocal()
    try:
        pay = db.get(Payment, payment_id)
        if not pay or pay.user_id != current_user.id:
            flash("Payment not found.", "error")
            return redirect(url_for("shop.list_packages"))

        ext = file.filename.rsplit(".", 1)[-1].lower()
        fname = f"{uuid.uuid4().hex}.{ext}"
        dest = os.path.join(current_app.config["UPLOAD_DIR"], fname)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        file.save(dest)
        rel_path = os.path.relpath(dest, os.getcwd()).replace("\\", "/")

        pay.slip_url = rel_path
        # ✅ change from draft -> pending when slip is uploaded (send to admin)
        pay.status = "pending"
        pay.verified_at = None

        db.add(pay)
        db.commit()
        flash("Slip uploaded. Sent to admin for review.", "success")
        return redirect(url_for("shop.payment_upload", payment_id=payment_id))
    finally:
        db.close()

# ✅ cancel button (allowed only when status is draft)
@bp.post("/payments/<int:payment_id>/cancel")
@login_required
def payment_cancel(payment_id: int):
    db = SessionLocal()
    try:
        pay = db.get(Payment, payment_id)
        if not pay or pay.user_id != current_user.id:
            flash("Payment not found.", "error")
            return redirect(url_for("shop.list_packages"))

        if pay.status != "draft":
            flash("Cannot cancel. This payment was already sent to admin or processed.", "error")
            return redirect(url_for("shop.payment_upload", payment_id=payment_id))

        pay.status = "cancelled"
        pay.updated_at = datetime.utcnow()
        db.add(pay)
        db.commit()
        flash("Payment request cancelled.", "success")
        return redirect(url_for("shop.list_packages"))
    finally:
        db.close()
