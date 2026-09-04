"""boc.py — SINH TỰ ĐỘNG, ĐỪNG SỬA TAY.

Sinh từ `worker/fb_pages.py` của repo selenova bằng `scripts/xuat_boc.py`.
Sửa ở đây là sửa vào bản sao: lần sinh sau đè mất, mà trong lúc đó runner bóc
một kiểu còn shno1 bóc một kiểu.

Chứa đúng phần ĐỌC ĐƯỢC GÌ TỪ FACEBOOK: lấy trang + bóc bài + chẩn đoán trang
trắng. KHÔNG chứa dedup, chấm scope, gửi tin — những thứ đó ở lại shno1.
"""
from __future__ import annotations

import base64
import binascii
import json
import random
import re
import time
from datetime import datetime, timedelta, timezone

import httpx

VN = timezone(timedelta(hours=7))


class FetchError(RuntimeError):
    """Không lấy được trang, hoặc lấy được nhưng bị đá về login."""


BASE = 'https://www.facebook.com'

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Accept-Language': 'vi-VN,vi;q=0.9,en-US;q=0.8', 'Sec-Fetch-Dest': 'document', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'none', 'Sec-Fetch-User': '?1', 'Upgrade-Insecure-Requests': '1', 'sec-ch-ua': '"Chromium";v="126", "Not:A-Brand";v="24"', 'sec-ch-ua-mobile': '?0', 'sec-ch-ua-platform': '"Windows"'}


_RE_MSG = re.compile('"message":\\{"text":"((?:[^"\\\\]|\\\\.)*)"')
_RE_TIME = re.compile('"creation_time":(\\d{10})')
_RE_URL = re.compile('"url":"(https:\\\\?/\\\\?/www\\.facebook\\.com\\\\?/[^"]*?posts\\\\?/pfbid[0-9A-Za-z]+)[^"]*"')
_RE_PFBID = re.compile('pfbid[0-9A-Za-z]{20,}')
_RE_PINNED = re.compile('"is_pinned":true')
_RE_STORY_ID = re.compile('"__typename":"Story",.{0,400}?"id":"([A-Za-z0-9+/=]{20,})"', re.S)
_RE_STORY_IDS = re.compile('^S:_I(\\d+):(\\d+)')
_RE_TITLE = re.compile('<title[^>]*>(.*?)</title>', re.S)
_RE_GROUP_POST_ID = re.compile('"post_id":"(\\d+)"')
_RE_GROUP_MSG = re.compile('"message":\\{"text":"((?:[^"\\\\]|\\\\.)*)"')
_RE_GROUP_TIME = re.compile('"creation_time":(\\d{10})')


def _pause() -> None:
    """Nghỉ giữa 2 page. Không phải để né chặn — để một lượt quét trông giống
    người đọc lần lượt mấy page, không phải một tràng request đều tăm tắp."""
    time.sleep(random.uniform(1.5, 4.0))


def _unescape_json_str(s: str) -> str:
    """Chuỗi trong payload là JSON đã escape (\\u1ec7, \\n, \\/). Cho json.loads
    giải đúng luật thay vì tự thay tay — tự thay là hỏng dấu tiếng Việt."""
    try:
        return json.loads(f'"{s}"')
    except json.JSONDecodeError:
        return s.replace("\\/", "/").replace("\\n", "\n")


def _tu_story_id(page: str) -> tuple[str, str] | None:
    """(khoá dedup, permalink) suy từ story id cho bài không có pfbid."""
    m = _RE_STORY_ID.search(page)
    if not m:
        return None
    raw = m.group(1)
    try:
        s = base64.b64decode(raw + "==").decode("utf-8", "ignore")
    except (ValueError, binascii.Error):
        return None
    ids = _RE_STORY_IDS.match(s)
    if not ids:
        return None
    page_id, post_id = ids.group(1), ids.group(2)
    return (f"sid:{post_id}",
            f"{BASE}/permalink.php?story_fbid={post_id}&id={page_id}")


def parse_group_stories(page: str, gid: str, gioi_han: int = 8) -> list[dict]:
    """Bóc các bài thấy được trong một group. [] = không bóc được bài nào.

    Trả về ĐÚNG hình dạng `parse_newest()` để mọi tầng sau dùng lại nguyên vẹn:
    dedup nội dung, link đăng ký, validate, chấm per-brief, push.
    """
    moc = [m.start() for m in _RE_GROUP_POST_ID.finditer(page)]
    if not moc:
        return []
    ra: list[dict] = []
    thay: set[str] = set()
    for a, b in zip(moc, moc[1:] + [len(page)]):
        lat = page[a:b]
        m = _RE_GROUP_MSG.search(lat)
        if not m:
            continue                      # ảnh/video không caption — không phải lỗi
        pid = _RE_GROUP_POST_ID.search(lat).group(1)
        if pid in thay:                   # mỗi bài xuất hiện nhiều lần trong payload
            continue
        thay.add(pid)
        text = _unescape_json_str(m.group(1)).strip()
        t = _RE_GROUP_TIME.search(lat)
        ts = int(t.group(1)) if t else None
        ra.append({
            "pfbid": f"sid:{pid}",
            "url": f"{BASE}/groups/{gid}/posts/{pid}/",
            "text": text,
            "creation_time": ts,
            "dang_luc": datetime.fromtimestamp(ts, VN) if ts else None,
            # Bài ghim của group nằm lẫn trong cùng danh sách và KHÔNG che bài mới
            # (group trả nhiều bài), nên không cần cảnh báo ghim như page.
            "ghim": False,
        })
        if len(ra) >= gioi_han:
            break
    return ra


def chan_doan_trang(page: str) -> str:
    """Bóc 0 bài thì hỏng ở ĐÂU? Trả 'page_mat' | 'doi_payload'.

    Đo thật 16/8, cùng một client httpx, cách nhau vài giây:

      DoanHoiKinhteLuatUFM   200 · 324.766 bytes · <title>Facebook</title>       · 0 bài
      slug bịa hoàn toàn     200 · 324.788 bytes · <title>Facebook</title>       · 0 bài
      doan.hoi.ufm           200 · 982.663 bytes · <title>Tuổi trẻ … UFM</title> · 1 bài

    Địa chỉ chết trả về ĐÚNG cái trang mà FB trả cho một địa chỉ bịa — lệch nhau 15
    bytes. Nên `<title>` trống trơn là dấu hiệu chắc chắn nhất phân biệt được hai
    bệnh cần hai cách chữa hoàn toàn khác nhau:

      · page_mat     — page đổi username / bị gỡ / bật giới hạn xem. Chữa bằng cách
                       sửa MỘT DÒNG địa chỉ trong `crawl_sources`, không đụng code.
      · doi_payload  — FB đổi cấu trúc dữ liệu. Chữa bằng sửa regex, việc của dev.

    Vì sao đáng tách: 15/8 page `DoanHoiKinhteLuatUFM` đổi tên thành
    `DoanHoiVienKinhteChinhtriQuocteUFM`, cảnh báo lại nói "FB nhiều khả năng đã đổi
    payload" — nghe như sự cố hạ tầng nên bị để trôi 36 tiếng, trong khi việc thật
    chỉ mất một phút. Lời báo sai làm hỏng thời gian phản ứng y như im lặng.
    """
    m = _RE_TITLE.search(page)
    ten = (m.group(1).strip() if m else "")
    return "doi_payload" if ten and ten.lower() != "facebook" else "page_mat"


def parse_newest(page: str) -> dict | None:
    """Bóc bài mới nhất trong khối prefetch. None = không thấy story nào."""
    m = _RE_MSG.search(page)
    if not m:
        return None
    text = _unescape_json_str(m.group(1)).strip()

    t = _RE_TIME.search(page)
    ts = int(t.group(1)) if t else None

    u = _RE_URL.search(page)
    url = _unescape_json_str(u.group(1)) if u else ""
    pf = _RE_PFBID.search(url) or _RE_PFBID.search(page)

    # KHOÁ DEDUP LUÔN ƯU TIÊN story id, KHÔNG dùng pfbid.
    # Sự cố 9/8: FB xoay alias pfbid cho CÙNG một bài (pfbid02QVtCv… → pfbid0LxF219x…,
    # cùng story id 1500063835493283, cùng giờ đăng, cùng 1797 ký tự). Khoá theo pfbid
    # nên bài cũ thành "bài mới" → chấm lại → đẩy → 30 sinh viên nhận trùng tin
    # Vietbuild lần hai. pfbid chỉ còn dùng để dựng URL.
    sid = _tu_story_id(page)
    if sid:
        khoa, url_sid = sid
        url = url or url_sid
    else:
        khoa = pf.group(0) if pf else None

    return {
        "pfbid": khoa,
        "url": url,
        "text": text,
        "creation_time": ts,
        "dang_luc": datetime.fromtimestamp(ts, VN) if ts else None,
        "ghim": bool(_RE_PINNED.search(page)),
    }


def fetch_page(c: httpx.Client, slug: str) -> str:
    try:
        r = c.get(f"{BASE}/{slug}")
    except httpx.HTTPError as e:
        raise FetchError(f"lỗi mạng: {e}") from e
    if r.status_code != 200:
        raise FetchError(f"HTTP {r.status_code}")
    if "/login" in str(r.url):
        raise FetchError("bị đá về login")
    return r.text
