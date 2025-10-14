# C:\File\CARCOM\backend\app\__init__.py
from flask import (
    Flask,
    jsonify,
    render_template,
    send_from_directory,
    Response,
    abort,
    request,
)
from flask_cors import CORS
from flask_wtf import CSRFProtect
from flask_login import LoginManager, current_user
from flask_wtf.csrf import generate_csrf
import os

from .config import load_config
from app.db import SessionLocal
from app.models import User

# ===== extra deps for image proxy =====
import requests
from urllib.parse import urlparse


login_manager = LoginManager()
csrf = CSRFProtect()


@login_manager.user_loader
def load_user(user_id: str):
    db = SessionLocal()
    try:
        return db.get(User, int(user_id))
    finally:
        db.close()


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    load_config(app)
    CORS(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    # ---------- Security headers ----------
    @app.after_request
    def add_security_headers(resp: Response):
        # ช่วยลดปัญหา referer / anti-hotlink บางราย
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        # ปลอดภัยและยืดหยุ่นพอสำหรับ dev/prod (อนุญาต https: เผื่อรูปภายนอกที่ยังไม่ได้ proxy)
        csp = resp.headers.get("Content-Security-Policy", "")
        if "img-src" not in csp:
            resp.headers["Content-Security-Policy"] = (
                "img-src 'self' data: blob: https:; "
                "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob: https:;"
            )
        return resp

    @app.context_processor
    def inject_globals():
        def is_admin_user():
            if not getattr(current_user, "is_authenticated", False):
                return False
            admins = app.config.get("ADMIN_USERNAMES", [])
            return (current_user.username or "").lower() in [x.lower() for x in admins]

        return {"csrf_token": generate_csrf, "is_admin_user": is_admin_user}

    # ----- Blueprints -----
    from app.routes.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix="/auth")

    from app.routes.shop import bp as shop_bp
    app.register_blueprint(shop_bp)

    from app.routes.admin import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # ===== Image Proxy (แก้ OpaqueResponseBlocking / anti-hotlink) =====
    # รองรับโดเมนภาพยอดฮิต + นโยบาย header ราย host
    ALLOWED_SUFFIXES = (
        ".icarcdn.com",     # one2car
        ".kaidee.com",      # kaidee
        ".carsome.co.th",   # carsome
    )

    HOST_POLICIES = [
        {
            "match": lambda host: host.endswith(".icarcdn.com"),
            "headers": {"Referer": "https://www.one2car.com/"},
        },
        {
            "match": lambda host: host.endswith(".kaidee.com"),
            "headers": {"Referer": "https://www.kaidee.com/"},
        },
        {
            "match": lambda host: host.endswith(".carsome.co.th"),
            # Cloudflare Image Resizing มักต้อง Accept image/*
            "headers": {
                "Referer": "https://www.carsome.co.th/",
                "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            },
        },
    ]

    UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )

    def _host_allowed(host: str) -> bool:
        if not host:
            return False
        host = host.lower()
        return any(host.endswith(suf) for suf in ALLOWED_SUFFIXES)

    def _headers_for_host(host: str) -> dict:
        base = {"User-Agent": UA}
        for pol in HOST_POLICIES:
            try:
                if pol["match"](host):
                    base.update(pol.get("headers", {}))
                    break
            except Exception:
                continue
        return base

    @app.get("/img-proxy")
    def img_proxy():
        u = (request.args.get("u") or "").strip()
        if not u:
            abort(400, "missing u")

        p = urlparse(u)
        if p.scheme not in ("http", "https"):
            abort(400, "bad scheme")

        host = (p.hostname or "").lower()
        if not _host_allowed(host):
            # แสดง host ที่โดนบล็อกให้อ่านง่ายใน dev
            abort(403, f"host not allowed: {host}")

        try:
            r = requests.get(
                u,
                headers=_headers_for_host(host),
                stream=True,
                timeout=10,
            )
        except requests.RequestException:
            abort(502, "fetch error")

        if r.status_code != 200:
            # debug: print(f"[img-proxy] upstream {host} -> {r.status_code} for {u}")
            abort(r.status_code)

        # ตั้ง Content-Type ให้ถูกต้อง (fallback จากนามสกุล)
        ct = r.headers.get("Content-Type", "")
        url_lower = u.lower()
        if (not ct) or ("image" not in ct):
            if url_lower.endswith(".png") or ".png?" in url_lower:
                ct = "image/png"
            elif url_lower.endswith((".jpg", ".jpeg")) or ".jpg?" in url_lower or ".jpeg?" in url_lower:
                ct = "image/jpeg"
            elif url_lower.endswith(".gif") or ".gif?" in url_lower:
                ct = "image/gif"
            else:
                ct = "image/webp"

        resp = Response(r.iter_content(64 * 1024), content_type=ct)
        resp.headers["Cache-Control"] = "public, max-age=86400, immutable"  # cache 1 วัน
        resp.headers["Content-Disposition"] = 'inline; filename="img"'
        return resp

    # ----- Health & Home -----
    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/")
    def home():
        return render_template("home.html")

    # ===== Serve uploaded slips =====python -m flask --app app:create_app --debug run
    @app.get("/uploads/<path:subpath>")
    def serve_uploads(subpath: str):
        # จะได้ /uploads/slips/<filename> ทำงานใน dev ได้แน่นอน
        root = os.path.join(os.getcwd(), "uploads")
        return send_from_directory(root, subpath)

    return app
