"""cao.py — CÁI VÒI. Ghé page Facebook bằng khách vãng lai, gửi HTML THÔ về n8n. Hết.

MỘT script, chạy ở BA nơi (đại tu 05/09/2026):
  · repo public `selenova-cao` (GHA, IP Azure, phút Actions miễn phí)   — nhiều page nhất
  · repo `selenova` private (GHA, cùng dải IP Azure, tốn phút)          — ít page hơn
  · shno1 (IP FPT residential — hạ tầng khác thật)                      — 3 page
Ba nơi làm ĐÚNG MỘT việc giống nhau. Chỗ này cố ý KHÔNG bóc, KHÔNG regex, KHÔNG sổ,
KHÔNG khoá Supabase/Telegram. Bóc là việc của n8n (Code node "Bóc Story"), dedup là
việc của bảng `fb_bai`, báo động là việc của n8n. Mất nguyên worker cũng không mất gì.

HAI ĐƯỜNG LẤY TRANG, thử theo thứ tự:
  1. httpx thuần — header giả Chrome, jar cookie rỗng, GET facebook.com/<slug>.
     Đo 05/09 trên 3 IP Azure: 17/17 page có username mở được, HTML ~1 MB chứa
     đúng một khối `"__typename":"Story"` (bài mới nhất).
  2. Playwright Chromium headless, vẫn KHÔNG login — chỉ khi (1) bị đẩy về /login.
     Đo 05/09: page id-số (`profile.php?id=…`) httpx bị đá cả 3 dạng URL, Chromium
     mở được. Page bật "phải đăng nhập" (KetnoiSvvaDn) thì cả hai đều thua → gói lỗi.
  Cả hai đường đều thua ⇒ vẫn GỬI gói (loi + da_login + title) để n8n báo Tuấn.

NGUỒN lấy từ đâu:
  NGUON_JSON  (env) — JSON array [{id, slug, name, kind, duong_dan, can_pw}]; n8n
              truyền vào input `nguon` của workflow_dispatch, hoặc để trong secret.
  --tu-db     — shno1: đọc crawl_sources where cao_o='shno1' (cần .env Supabase).

Chạy:
  python cao.py --kho            # cào thật, in tóm tắt, KHÔNG đẩy
  python cao.py                  # đẩy về n8n (N8N_URL + N8N_TOKEN)
  python cao.py --tu-db          # shno1: nguồn từ DB
  python cao.py --luu DIR        # lưu HTML ra DIR để soi (kèm --kho)
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
try:  # shno1 có .env; runner GHA không có, biến đi qua Actions env
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, ".env"))
except ImportError:
    pass

VN = timezone(timedelta(hours=7))
BASE = "https://www.facebook.com"
HET_GIO = 30
WORKER = os.environ.get("CAO_WORKER") or (
    "private" if os.environ.get("GITHUB_REPOSITORY", "").endswith("/selenova")
    else "public" if os.environ.get("GITHUB_ACTIONS") else "shno1")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
# Đủ header trình duyệt — UA trần là FB trả 400 (dò 9/8). mbasic./m. đá về /login.
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="126", "Not:A-Brand";v="24"',
    "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
}


class FetchError(RuntimeError):
    pass


def _pause() -> None:
    """Nghỉ giữa 2 page — để một lượt trông như người đọc lần lượt vài page."""
    time.sleep(random.uniform(1.5, 4.0))


def _duong_dan(src: dict) -> str:
    """Phần sau facebook.com/ — ưu tiên `duong_dan`, rồi `slug`, rồi bóc từ `url`."""
    d = src.get("duong_dan") or src.get("slug")
    if not d and src.get("url"):
        d = src["url"].split("facebook.com/", 1)[-1].strip("/")
    return (d or "").strip("/")


# ── đường 1: httpx ─────────────────────────────────────────────────────────────
def mo_client() -> httpx.Client:
    """Jar RỖNG mỗi lượt — cố ý. Runner đổi IP mỗi run nên cookie mới đi kèm IP mới
    là hình dạng tự nhiên; shno1 cũng dùng jar rỗng cho đồng nhất (3 page/lượt,
    ~150 GET/ngày, thấp hơn nhiều mức 240 đã đo sạch)."""
    c = httpx.Client(headers=HEADERS, timeout=HET_GIO, follow_redirects=True)
    c.get(BASE + "/")          # bootstrap datr/sb — thiếu là FB trả 400 cho mọi GET sau
    return c


def fetch_httpx(c: httpx.Client, duong_dan: str) -> str:
    try:
        r = c.get(f"{BASE}/{duong_dan}")
    except httpx.HTTPError as e:
        raise FetchError(f"lỗi mạng: {e}") from e
    if r.status_code != 200:
        raise FetchError(f"HTTP {r.status_code}")
    if "/login" in str(r.url):
        raise FetchError("bị đá về login")
    return r.text


# ── đường 2: Playwright vãng lai ───────────────────────────────────────────────
_pw = None


def _bat_pw():
    """Mở Chromium MỘT lần cho cả lượt. Cài thiếu thì tự cài (GHA) — trên shno1 cài
    sẵn vào .venv một lần: `pip install playwright && playwright install chromium`."""
    global _pw
    if _pw is not None:
        return _pw
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if not os.environ.get("GITHUB_ACTIONS"):
            raise FetchError("thiếu playwright — cài vào .venv rồi chạy lại")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "playwright"], check=True)
        subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
                       check=True)
        import importlib
        importlib.invalidate_caches()      # gói vừa cài trong cùng tiến trình
        from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(locale="vi-VN", user_agent=UA, viewport={"width": 1280, "height": 900})
    _pw = (p, b, ctx)
    return _pw


def fetch_pw(duong_dan: str) -> str:
    """Mọi lỗi (cài thiếu, chromium chưa có, timeout, crash tab) đều gói thành
    FetchError — một page hỏng ở đường PW không được làm chết cả lượt."""
    pg = None
    try:
        _, _, ctx = _bat_pw()
        pg = ctx.new_page()
        pg.goto(f"{BASE}/{duong_dan}", wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(5000)          # cho JS dựng xong khối prefetch
        if "/login" in pg.url:
            raise FetchError("bị đá về login (cả PW)")
        return pg.content()
    except FetchError:
        raise
    except Exception as e:  # noqa: BLE001
        raise FetchError(f"PW lỗi: {type(e).__name__}: {str(e)[:120]}") from e
    finally:
        if pg is not None:
            pg.close()


def _tat_pw() -> None:
    global _pw
    if _pw:
        p, b, ctx = _pw
        try:
            ctx.close(); b.close(); p.stop()
        except Exception:  # noqa: BLE001
            pass
        _pw = None


# ── một nguồn ──────────────────────────────────────────────────────────────────
def mot_nguon(c: httpx.Client, src: dict) -> dict:
    """LUÔN trả dict, không ném — một page hỏng không được làm chết cả lượt, và
    bản thân "hỏng" cũng là dữ liệu n8n cần để báo."""
    dd = _duong_dan(src)
    ra = {"id": src.get("id"), "slug": src.get("slug") or dd, "name": src.get("name"),
          "kind": src.get("kind", "page"), "duong": None, "bytes": 0,
          "da_login": False, "loi": None, "html": None}
    try:
        ra["html"] = fetch_httpx(c, dd)
        ra["duong"] = "httpx"
    except FetchError as e1:
        ra["loi"] = str(e1)
        ra["da_login"] = "login" in str(e1)
        # PW chỉ đáng thử khi httpx bị đá login (cấu trúc client), không phải lỗi mạng.
        if ra["da_login"] or src.get("can_pw"):
            try:
                ra["html"] = fetch_pw(dd)
                ra["duong"], ra["loi"], ra["da_login"] = "pw", None, False
            except FetchError as e2:
                ra["loi"] = f"{e1} · {e2}"
                ra["da_login"] = "login" in str(e2)
    if ra["html"]:
        ra["bytes"] = len(ra["html"])
    return ra


# ── đẩy về n8n ─────────────────────────────────────────────────────────────────
NGHI_THU_LAI = (5, 15)   # giây nghỉ trước lần thử 2, 3


def day_goi(url: str, token: str, goi: dict, slug: str) -> bool:
    """POST một gói về n8n, thử lại tối đa 3 lần khi lỗi THOÁNG QUA (timeout, lỗi
    mạng, 5xx — kể cả 520/524 của Cloudflare). Lỗi 4xx (token sai, 413) thì thôi.

    Vì sao: run private 06/09 09:00 đỏ vì 2/5 gói dính 520 + read timeout dù n8n xử
    lý mỗi gói 1–2 s và các gói xen kẽ vẫn tới — nghẽn ở đường Azure→Cloudflare→
    origin, không phải n8n. Thử lại một lần là qua; n8n upsert fb_bai theo sid nên
    gói tới hai lần cũng vô hại."""
    for lan in range(1, len(NGHI_THU_LAI) + 2):
        try:
            resp = httpx.post(url, json=goi, timeout=120, headers={"X-Selenova-Token": token})
            resp.raise_for_status()
            if lan > 1:
                print(f"     ↻ {slug}: đẩy được ở lần {lan}", file=sys.stderr)
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500:
                print(f"     ✗ {slug}: đẩy về n8n hỏng, không thử lại: {str(e).splitlines()[0]}", file=sys.stderr)
                return False
            loi = str(e).splitlines()[0]
        except httpx.HTTPError as e:      # timeout, đứt kết nối
            loi = f"{type(e).__name__}: {e}".splitlines()[0]
        if lan <= len(NGHI_THU_LAI):
            print(f"     ⚠ {slug}: lần {lan} hỏng ({loi[:80]}) — nghỉ {NGHI_THU_LAI[lan - 1]}s rồi thử lại",
                  file=sys.stderr)
            time.sleep(NGHI_THU_LAI[lan - 1])
    print(f"     ✗ {slug}: đẩy về n8n hỏng sau {lan} lần: {loi}", file=sys.stderr)
    return False


# ── nguồn ──────────────────────────────────────────────────────────────────────
def nguon_tu_db() -> list[dict]:
    import supa  # chỉ shno1 mới có .env Supabase
    rows = supa._data(supa._client.get(
        f"{supa.REST}/crawl_sources",
        params={"select": "id,name,url,kind,can_pw", "is_active": "eq.true",
                "cao_o": f"eq.{WORKER}", "order": "name"})) or []
    return [{"id": r["id"], "name": r["name"], "kind": r["kind"], "can_pw": r.get("can_pw"),
             "slug": r["url"].split("facebook.com/", 1)[-1].strip("/")} for r in rows]


def main() -> int:
    kho = "--kho" in sys.argv
    luu = sys.argv[sys.argv.index("--luu") + 1] if "--luu" in sys.argv else None
    if "--tu-db" in sys.argv:
        nguon = nguon_tu_db()
    else:
        try:
            nguon = json.loads(os.environ.get("NGUON_JSON") or "[]")
        except json.JSONDecodeError as e:
            print(f"NGUON_JSON hỏng: {e}", file=sys.stderr)
            return 2
    if not nguon:
        print("Không có nguồn nào để ghé.", file=sys.stderr)
        return 2

    ip = ""
    try:
        ip = httpx.get("https://api.ipify.org", timeout=15).text.strip()
    except httpx.HTTPError:
        pass

    url, token = os.environ.get("N8N_URL"), os.environ.get("N8N_TOKEN")
    if not kho and (not url or not token):
        print("thiếu N8N_URL/N8N_TOKEN — không đẩy được.", file=sys.stderr)
        return 2
    run_id = os.environ.get("GITHUB_RUN_ID", datetime.now(VN).strftime("%Y%m%d%H%M"))
    repo = os.environ.get("GITHUB_REPOSITORY", "shno1")

    c = mo_client()
    ket, day_hong = [], 0
    try:
        for i, src in enumerate(nguon):
            r = mot_nguon(c, src)
            ket.append(r)
            print(f"  {r['slug']:36} {r['bytes']:>9,}b  {r['duong'] or '—':5} {r['loi'] or 'ok'}")
            if luu and r["html"]:
                os.makedirs(luu, exist_ok=True)
                ten = re.sub(r"[^A-Za-z0-9._-]+", "_", r["slug"])
                with open(os.path.join(luu, f"{ten}.html"), "w", encoding="utf-8") as f:
                    f.write(r["html"])
            # ĐẨY TỪNG PAGE MỘT GÓI, ngay khi ghé xong. Một HTML ~1 MB (PW còn to
            # hơn); gom 9 page = ~10 MB một POST, sát trần 16 MB mặc định của n8n —
            # quá là 413 và mất nguyên lượt. Từng gói thì một gói hỏng chỉ mất một page.
            if not kho:
                goi = {"luc": datetime.now(VN).isoformat(), "ip": ip, "worker": WORKER,
                       "repo": repo, "run_id": run_id, "ket": [r]}
                if not day_goi(url, token, goi, r["slug"]):
                    day_hong += 1
            if i < len(nguon) - 1:
                _pause()
    finally:
        c.close()
        _tat_pw()

    mo = sum(1 for r in ket if r["html"])
    print(f"\nIP {ip} · worker {WORKER} · run {run_id} · ghé {len(ket)} · mở được {mo} · "
          f"PW {sum(1 for r in ket if r['duong'] == 'pw')} · hỏng {len(ket) - mo}"
          + ("" if kho else f" · đẩy hỏng {day_hong}"))
    # ĐẨY HỎNG THÌ PHẢI ĐỎ: worker không có sổ để thử lại, im ở đây là n8n tưởng
    # "chưa tới giờ" chứ không biết là mất gói. Đỏ để còn nhìn thấy ở tab Actions.
    return 1 if day_hong else 0


if __name__ == "__main__":
    raise SystemExit(main())
