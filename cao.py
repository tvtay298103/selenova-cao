"""cao.py — CÁI VÒI. Lấy trang Facebook, bóc bài, đẩy về n8n. Hết.

Chỗ này CỐ Ý KHÔNG BIẾT GÌ về dedup, scope, ai nhận tin. Nó không có sổ, không
nhớ lượt trước, không nói chuyện với Supabase, không giữ khoá nào của hệ. Mất
nguyên cái runner cũng không mất dữ liệu và không lộ gì.

Vì sao tách ra khỏi shno1 (04/09/2026): tuyến cào đứng trên IP nhà, và IP nhà
là thứ đắt nhất trong hệ — mất nó là mất luôn khả năng đọc Facebook. Runner GHA
mỗi lượt một IP mới, hỏng thì lượt sau tự lành, không có gì để mất.

BIẾN MÔI TRƯỜNG (đặt bằng Actions secret, KHÔNG commit):
  NGUON_JSON   JSON array các nguồn phải ghé lượt này. Để trong secret chứ không
               để trong repo vì repo public thì danh sách page cũng public theo.
  N8N_URL      webhook n8n nhận kết quả.
  N8N_TOKEN    token chia sẻ, n8n đối chiếu để không ai khác đẩy rác vào.

  python cao.py           # chạy thật, có đẩy
  python cao.py --kho     # thử khô: cào thật, IN ra, KHÔNG đẩy
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import httpx

import boc

HET_GIO = 30


def mo_client() -> httpx.Client:
    """Client khách. Jar RỖNG mỗi run — khác shno1, và cố ý.

    shno1 giữ `datr` bền giữa các lượt vì ở đó cookie mới mỗi lượt sẽ thành 48
    "người lạ" cùng đổ ra từ MỘT IP nhà, bất thường hơn một người đọc quen. Trên
    runner thì ngược lại: mỗi lượt đã là một IP khác rồi, nên cookie mới đi kèm
    IP mới mới là hình dạng tự nhiên. Bê nguyên jar bền sang đây thành ra một
    cookie duy nhất nhảy qua 96 IP một ngày — đó mới là thứ đáng ngờ.
    """
    c = httpx.Client(headers=boc.HEADERS, timeout=HET_GIO, follow_redirects=True)
    c.get(boc.BASE + "/")          # bootstrap datr/sb
    return c


def mot_nguon(c: httpx.Client, src: dict) -> dict:
    """Ghé một nguồn. LUÔN trả về dict, không ném — một page hỏng không được
    làm chết cả lượt, và bản thân "hỏng" cũng là dữ liệu shno1 cần biết."""
    slug = src["slug"]
    ra = {"id": src.get("id"), "slug": slug, "name": src.get("name"),
          "kind": src.get("kind", "page"), "http": None, "bytes": 0,
          "da_login": False, "benh": None, "loi": None, "posts": []}
    try:
        html = boc.fetch_page(c, src.get("duong_dan") or slug)
    except boc.FetchError as e:
        ra["loi"] = str(e)
        ra["da_login"] = "login" in str(e)
        return ra

    ra["http"] = 200
    ra["bytes"] = len(html)
    if src.get("kind") == "group":
        ds = boc.parse_group_stories(html, str(src["duong_dan"]).split("/")[-1])
    else:
        p1 = boc.parse_newest(html)
        ds = [p1] if p1 else []

    if not ds:
        # Y HỆT luật canary của shno1: 200 mà bóc 0 bài KHÔNG phải "page không
        # đăng gì". Chẩn đoán ở đây vì cần cái HTML, nhưng CẢNH BÁO thì để shno1
        # bắn — Telegram token không được phép có mặt trên runner.
        ra["benh"] = boc.chan_doan_trang(html)
        return ra

    for p in ds:
        ra["posts"].append({
            "pfbid": p["pfbid"],
            "url": p["url"],
            "text": p["text"],
            "creation_time": p["creation_time"],
            "dang_luc": p["dang_luc"].isoformat() if p.get("dang_luc") else None,
            "ghim": p.get("ghim", False),
        })
    return ra


def main() -> int:
    kho = "--kho" in sys.argv
    try:
        nguon = json.loads(os.environ["NGUON_JSON"])
    except (KeyError, json.JSONDecodeError) as e:
        print(f"NGUON_JSON thiếu hoặc hỏng: {e}", file=sys.stderr)
        return 2
    if not nguon:
        print("NGUON_JSON rỗng — không có gì để ghé.", file=sys.stderr)
        return 2

    ip = ""
    try:
        ip = httpx.get("https://api.ipify.org", timeout=15).text.strip()
    except httpx.HTTPError:
        pass

    c = mo_client()
    ket = []
    try:
        for i, src in enumerate(nguon):
            r = mot_nguon(c, src)
            ket.append(r)
            trang_thai = (r["loi"] or r["benh"] or f"{len(r['posts'])} bài")
            print(f"  {r['slug']:36} {r['bytes']:>9,}b  {trang_thai}")
            if i < len(nguon) - 1:
                boc._pause()
    finally:
        c.close()

    goi = {
        "luc": datetime.now(boc.VN).isoformat(),
        "ip": ip,
        "repo": os.environ.get("GITHUB_REPOSITORY", "?"),
        "run_id": os.environ.get("GITHUB_RUN_ID", "?"),
        "ket": ket,
    }
    boc_duoc = sum(1 for r in ket if r["posts"])
    da_login = sum(1 for r in ket if r["da_login"])
    print(f"\nIP {ip} · ghé {len(ket)} · bóc được {boc_duoc} · "
          f"bị đá về login {da_login}")

    if kho:
        print(json.dumps(goi, ensure_ascii=False, indent=1)[:4000])
        return 0

    url, token = os.environ.get("N8N_URL"), os.environ.get("N8N_TOKEN")
    if not url or not token:
        print("thiếu N8N_URL/N8N_TOKEN — không đẩy được.", file=sys.stderr)
        return 2
    try:
        r = httpx.post(url, json=goi, timeout=60,
                       headers={"X-Selenova-Token": token})
        r.raise_for_status()
    except httpx.HTTPError as e:
        # ĐẨY HỎNG THÌ PHẢI ĐỎ CI. Lượt cào coi như mất — không có sổ trên runner
        # để thử lại, mà im lặng ở đây thì shno1 tưởng "chưa tới giờ" chứ không
        # biết là mất. Đỏ để còn nhìn thấy trong tab Actions.
        print(f"đẩy về n8n hỏng: {e}", file=sys.stderr)
        return 1
    print(f"đã đẩy về n8n: HTTP {r.status_code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
