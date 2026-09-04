# selenova — vòi cào

Lấy trang Facebook công khai, bóc bài mới nhất, đẩy JSON về n8n. **Hết.**

Chỗ này cố ý *không* biết dedup, không biết chấm scope, không biết ai nhận tin,
không giữ khoá Supabase/Telegram nào. Toàn bộ những thứ đó ở lại máy nhà.
Mất nguyên repo này cũng không mất dữ liệu và không lộ gì.

## Vì sao tồn tại

Tuyến cào trước đây chạy trên một máy ở nhà. Máy đó ổn, nhưng nó đứng trên **một
IP duy nhất** — và IP là thứ đắt nhất trong hệ: mất nó là mất luôn khả năng đọc.
Đo 21-25/08/2026: khi tải từ IP đó tăng ~280 → ~420 lượt/ngày thì Facebook bắt
đầu đá về trang đăng nhập, leo 3 → 9 page/ngày.

Runner GitHub mỗi lượt chạy trên một IP khác. Không có gì tích luỹ, nên cũng
không có gì để mất.

## Chạy tay

```bash
pip install "httpx>=0.27"
NGUON_JSON='[{"slug":"ten.page","kind":"page","name":"Tên"}]' python cao.py --kho
```

`--kho` = cào thật, in ra, **không** đẩy đi đâu.

## File

| file | vai trò |
|---|---|
| `cao.py` | vòi: lấy → bóc → đẩy |
| `boc.py` | **SINH TỰ ĐỘNG, đừng sửa tay** — xem đầu file |

## Cấu hình (Actions secrets, không commit)

| tên | là gì |
|---|---|
| `NGUON_JSON` | danh sách nguồn phải ghé. Để trong secret chứ không để trong repo — repo public thì danh sách cũng public theo. |
| `N8N_URL` | webhook nhận kết quả |
| `N8N_TOKEN` | token chia sẻ, để không ai khác đẩy rác vào |
