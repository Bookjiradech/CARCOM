# app/routes/img_proxy.py
from urllib.parse import urlparse
import requests
from flask import Blueprint, request, Response, abort

bp = Blueprint("imgproxy", __name__)

ALLOWED_HOSTS = {
    "img1.icarcdn.com", "img2.icarcdn.com", "img3.icarcdn.com",
    "img4.icarcdn.com", "img5.icarcdn.com"
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

@bp.get("/img-proxy")
def img_proxy():
    u = request.args.get("u", "").strip()
    if not u:
        abort(400, "missing u")

    p = urlparse(u)
    if p.scheme not in ("http", "https"):
        abort(400, "bad scheme")
    if p.hostname not in ALLOWED_HOSTS:
        abort(403, "host not allowed")

    try:
        r = requests.get(
            u,
            headers={
                "User-Agent": UA,
                # Add referer of the original site to pass anti-hotlink checks
                "Referer": "https://www.one2car.com/",
            },
            stream=True,
            timeout=10,
        )
    except requests.RequestException:
        abort(502, "fetch error")

    if r.status_code != 200:
        abort(r.status_code)

    # Guess Content-Type if not provided
    ct = r.headers.get("Content-Type", "")
    if not ct or "image" not in ct:
        # Guess from extension
        if u.lower().endswith(".png") or ".png?" in u.lower():
            ct = "image/png"
        elif u.lower().endswith((".jpg", ".jpeg")) or ".jpg" in u.lower() or ".jpeg" in u.lower():
            ct = "image/jpeg"
        else:
            ct = "image/webp"

    resp = Response(r.iter_content(64 * 1024), content_type=ct)
    # cache 1 day
    resp.headers["Cache-Control"] = "public, max-age=86400, immutable"
    # inline to prevent forced download
    resp.headers["Content-Disposition"] = 'inline; filename="img"'
    return resp
