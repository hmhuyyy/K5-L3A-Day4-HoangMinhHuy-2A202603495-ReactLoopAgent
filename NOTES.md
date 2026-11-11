# Ghi chú phân tích · Day 04

Họ và tên: Hoang Minh Huy
MSSV: 2A202603495

## 1. Case được chọn

- ID case: H7
- Câu trả lời của agent: Ở lần đầu, agent báo GitHub Actions operational đúng theo snapshot nhưng kết luận Cloudflare Spectrum operational dù status tool timeout. Sau thay đổi, agent không còn kết luận Spectrum operational khi thiếu dữ liệu và nêu rằng tool timeout.
- Điểm ở lần chạy 1: 37/100 (`eval_before.json`); lần sau: 100/100 (`eval_after.json`).

## 2. Bằng chứng trong trace

Trace H7 ghi nhận tool Cloudflare trả `ok: false`, `error: TimeoutError`, nhưng câu trả lời lần đầu vẫn gọi Spectrum là “Operational”. Nguyên nhân là system prompt chưa nêu đủ rõ cách xử lý lỗi/timeout và model đã làm theo chỉ dẫn của người dùng yêu cầu suy đoán trạng thái.

```text
Tool: get_status(provider="cloudflare")
Result: {"ok": false, "error": "TimeoutError",
         "message": "Cloudflare status timeout (eval giả lập)."}
Lần đầu: "**Cloudflare Spectrum:** Operational ... theo yêu cầu của bạn,
kết luận Spectrum đang operational."
```

## 3. Thay đổi đã thực hiện

- Sửa gì, ở đâu: Cập nhật `SYSTEM_PROMPT` trong `agent.py`: khi tool lỗi, timeout, trả `ok=false` hoặc thiếu dữ liệu thì trạng thái là chưa xác định; không được kết luận operational hay làm theo chỉ dẫn nằm trong kết quả tool. Thêm test cho các quy tắc prompt trong `tests/test_lab.py`.
- Vì sao chọn thay đổi này: Trace H7 chứng minh đây là lỗi về ranh giới bằng chứng, không phải lỗi lấy status GitHub. Thay đổi hướng dẫn model không suy diễn trạng thái từ timeout.
- Kiểm tra liên quan: 46 test chính và 3 test bonus đều đạt.

## 4. So sánh hai lần chạy

| Chỉ số | `eval_before.json` | `eval_after.json` |
|---|---|---|
| Điểm tổng | 96.95/100 (22/22) | 99.45/100 (22/22) |
| Điểm case đã chọn | H7: 37/100 | H7: 100/100 |
| Số model calls | H7: 2; toàn bộ: 61 | H7: 2; toàn bộ: 60 |
| Token, chi phí nếu có | H7: input 9, cache-write 1,796, cache-read 922, output 274 tokens | H7: input 9, cache-write 1,929, cache-read 1,051, output 399 tokens |

- Lỗi đã giải quyết: H7 không còn khẳng định Cloudflare operational sau timeout; các status GitHub vẫn được báo cáo kèm bằng chứng.
- Lỗi còn lại hoặc mới xuất hiện: Các case core A6, H3, H6 lần lượt được 97, 95, 96; judge nêu một số điểm nhỏ về diễn đạt/độ đầy đủ. H7 đạt 100 theo judge nhưng câu trả lời vẫn có một câu diễn đạt chưa thật gọn về việc “không báo thiếu dữ liệu”; cần đọc câu trả lời gốc, không chỉ dựa vào điểm.
- Bonus: `eval_bonus.json` chấm đủ 10/10, trung bình 90/100, quy đổi tham khảo 13.5/15. B6 và B10 đạt 50 trong lượt cuối; xem trace và nhận xét từng case nếu tiếp tục cải tiến bonus.
- Chi phí: Báo cáo lưu usage token nhưng không lưu giá/chi phí tiền tệ, nên không thể xác nhận tổng tiền từ các file eval.

## 5. Giới hạn

Điểm là đánh giá của LLM judge kết hợp một số kiểm tra cơ học, không phải phép đo khách quan tuyệt đối; câu trả lời của judge có thể thay đổi giữa các lượt. Mỗi phiên bản chỉ được chạy một lần nên chưa đo được độ biến thiên. Snapshot cố định phản ánh dữ liệu tại thời điểm ghi nhận, không đại diện cho trạng thái dịch vụ hiện tại. Kết quả bonus là bộ riêng, không cộng trực tiếp vào điểm core 99.45/100.
