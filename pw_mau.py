"""pw_mau.py — TẠM 05/09: Playwright VÃNG LAI (không login) cho các nguồn httpx bị đá về login.
Lưu HTML + screenshot ra mau/. Không đẩy đi đâu. Xoá sau khi soi."""
import json, os, sys, time
from playwright.sync_api import sync_playwright

NGUON = json.loads(os.environ["NGUON_TAY"])
os.makedirs("mau", exist_ok=True)
tomtat = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(locale="vi-VN", viewport={"width": 1280, "height": 900},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
    for src in NGUON:
        slug = src["slug"]; url = "https://www.facebook.com/" + src["duong_dan"]
        r = {"slug": slug, "url": url, "final_url": None, "bytes": 0, "da_login": False, "loi": None, "title": None}
        pg = ctx.new_page()
        try:
            resp = pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(6000)          # cho JS dựng xong feed
            try:
                # đóng popup "Đăng nhập" nếu FB chèn lên trên
                pg.keyboard.press("Escape"); pg.wait_for_timeout(800)
            except Exception: pass
            r["http"] = resp.status if resp else None
            r["final_url"] = pg.url
            r["da_login"] = "/login" in pg.url
            r["title"] = pg.title()
            html = pg.content()
            r["bytes"] = len(html)
            open(f"mau/{slug}.pw.html", "w", encoding="utf-8").write(html)
            pg.screenshot(path=f"mau/{slug}.png", full_page=False)
            # cuộn 2 nấc rồi lưu thêm bản sau khi cuộn — feed có thể nạp thêm bài
            for _ in range(2):
                pg.mouse.wheel(0, 1500); pg.wait_for_timeout(2500)
            open(f"mau/{slug}.pw.scroll.html", "w", encoding="utf-8").write(pg.content())
        except Exception as e:
            r["loi"] = str(e)[:300]
        finally:
            pg.close()
        print(f"  {slug:24} http={r.get('http')} bytes={r['bytes']:,} login={r['da_login']} title={r['title']!r} loi={r['loi']}")
        tomtat.append(r); time.sleep(3)
    b.close()
json.dump(tomtat, open("mau/_tomtat.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
