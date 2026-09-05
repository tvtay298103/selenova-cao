# selenova-cao — worker cào "public"

Ghé page Facebook công khai bằng **khách vãng lai** (httpx, rơi sang Playwright khi bị
đá login), gửi **HTML thô** về n8n. **Hết.**

Repo này cố ý *không* bóc bài, không dedup, không chấm scope, không biết ai nhận tin,
không giữ khoá Supabase/Telegram nào. Bóc là việc của n8n, sổ dedup là bảng `fb_bai`,
gửi tin là việc của máy nhà. Mất nguyên repo này cũng không mất dữ liệu, không lộ gì.

## Vì sao public

Phút Actions của repo public **miễn phí**, nên chỗ này gánh phần lớn page và cả bậc
Playwright (cài Chromium ~40s/run) mà không phải đắn đo. Mỗi run một IP Azure mới —
không có gì tích luỹ, nên cũng không có gì để mất.

## Nhịp & nguồn

Không có `schedule:`. **n8n** (workflow *Selenova — FB cào 00 Nhịp*) bấm
`workflow_dispatch` mỗi 15' (06h–22h VN) và truyền danh sách nguồn qua input `nguon`,
đọc từ `crawl_sources.cao_o = 'public'`. Thêm/tắt nguồn = sửa DB, không đụng repo.

## `cao.py` là BẢN CHÉP

Nguồn sự thật là `worker/cao.py` trong repo `selenova` (private). Sửa ở đó rồi chép
sang đây — đừng sửa tay bản này. Ba worker (public · selenova private · shno1) chạy
cùng một file.

## Chạy tay

```bash
pip install -r requirements.txt
NGUON_JSON='[{"slug":"ten.page","kind":"page","name":"Tên"}]' python cao.py --kho
```

`--kho` = cào thật, in tóm tắt, **không** đẩy đi đâu. `--luu DIR` lưu HTML ra soi.

## Secrets

| tên | là gì |
|---|---|
| `N8N_URL` | webhook nhận gói (`…/webhook/selenova-fb-cao`) |
| `N8N_TOKEN` | token chia sẻ, n8n đối chiếu để không ai khác đẩy rác vào |
