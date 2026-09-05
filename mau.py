"""mau.py — LẤY MẪU TẠM (05/09/2026). Ghé đủ nguồn y hệt cao.py (jar rỗng, cùng
HEADERS, cùng _pause) nhưng LƯU HTML THÔ ra thư mục mau/ để soi payload bằng mắt.
KHÔNG đẩy n8n, không đụng sổ dedup. Xoá file này + mau.yml khi lấy mẫu xong.
"""
import json, os, sys
import httpx
import boc

nguon = json.loads(os.environ["NGUON_JSON"])
os.makedirs("mau", exist_ok=True)
c = httpx.Client(headers=boc.HEADERS, timeout=30, follow_redirects=True)
c.get(boc.BASE + "/")
tomtat = []
for i, src in enumerate(nguon):
    slug = src["slug"]; kind = src.get("kind", "page")
    r = {"slug": slug, "kind": kind, "duong_dan": src.get("duong_dan"), "bytes": 0, "loi": None, "parse": None}
    try:
        html = boc.fetch_page(c, src.get("duong_dan") or slug)
        r["bytes"] = len(html)
        with open(f"mau/{slug}.html", "w", encoding="utf-8") as f:
            f.write(html)
        if kind == "group":
            r["parse"] = boc.parse_group_stories(html, str(src["duong_dan"]).split("/")[-1])
        else:
            r["parse"] = boc.parse_newest(html)
        if not r["parse"]:
            r["benh"] = boc.chan_doan_trang(html)
    except Exception as e:  # noqa
        r["loi"] = str(e)
    print(f"  {slug:36} {r['bytes']:>9,}b  {r['loi'] or (r.get('benh') or 'ok')}")
    tomtat.append(r)
    if i < len(nguon) - 1:
        boc._pause()
c.close()
with open("mau/_tomtat.json", "w", encoding="utf-8") as f:
    json.dump(tomtat, f, ensure_ascii=False, indent=1, default=str)
