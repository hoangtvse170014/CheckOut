# Trạng Thái Alert Email - Tại Sao Không Nhận Được Mail

## Vấn Đề Đã Phát Hiện

### ✅ Email Config - OK
- Email đã được enable: `True`
- Channel: `email`
- SMTP Host: `smtp.gmail.com`
- From: `meragroup.tech@gmail.com`
- To: `viethoanggm2003@gmail.com`
- Password: Đã set

### ✅ Missing Period - Đã Tạo
- Missing period ID: 23
- Start time: 2026-01-09 08:30:00
- Duration: 205.3 phút (> 30.5 phút) ✅
- Session: morning
- Status: ACTIVE

### ⚠️ Phase Hiện Tại - LUNCH_BREAK
- Current time: 11:55:58
- Phase: LUNCH_BREAK (11:55-13:15)
- Alert check bị SKIP trong phase này

## Lý Do Không Nhận Được Mail

### 1. Alert Check Bị Skip Trong LUNCH_BREAK
- Alert check chỉ chạy trong:
  - `REALTIME_MORNING` (08:30-11:55)
  - `AFTERNOON_MONITORING` (13:15-23:59)
- Hiện tại đang ở `LUNCH_BREAK` (11:55-13:15) → Alert check bị skip

### 2. Alert Check Chạy Mỗi 30 Phút
- Alert check chạy vào các thời điểm: 09:00, 09:30, 10:00, 10:30, 11:00, 11:30, ...
- Nếu missing period được tạo sau thời điểm alert check → Phải đợi lần check tiếp theo

### 3. Missing Period Có Thể Không Được Tạo Tự Động Từ Sáng
- PhaseManager tạo missing period mỗi 1 phút
- Nhưng nếu app restart, `active_missing_periods` dict bị reset
- Missing period trong database vẫn còn nhưng không được track trong memory

## Giải Pháp

### Ngay Lập Tức (Để Test)

1. **Đợi đến 13:15** (sau LUNCH_BREAK):
   - Phase sẽ chuyển sang `AFTERNOON_MONITORING`
   - Alert check sẽ chạy lại
   - Nếu missing period đủ 30.5 phút → Mail sẽ được gửi

2. **Hoặc force trigger alert check** (đã tạo missing period từ 08:30):
   - Missing period đã đủ 205 phút (> 30.5 phút)
   - Khi alert check chạy sau 13:15 → Mail sẽ được gửi

### Về Lâu Dài

1. **PhaseManager tự động tạo missing period**:
   - Đảm bảo PhaseManager scheduler đang chạy
   - Kiểm tra log để xem PhaseManager có tạo missing period không

2. **Alert check interval**:
   - Hiện tại: Mỗi 30 phút
   - Có thể giảm xuống 1 phút để test (nhưng sẽ spam nếu không có cooldown)

## Timeline Dự Kiến

```
11:55-13:15: LUNCH_BREAK → Alert check bị skip
13:15: Chuyển sang AFTERNOON_MONITORING
13:15: Alert check chạy lần đầu
  - Missing period duration: ~280 phút (> 30.5 phút) ✅
  - Missing count: 3 (> 0) ✅
  - Email enabled: True ✅
  → 📧 MAIL SẼ ĐƯỢC GỬI!
```

## Kiểm Tra

Sau 13:15, chạy:
```bash
python force_alert_check_now.py
```

hoặc đợi alert check tự động chạy (mỗi 30 phút).
