# Thời Điểm Gửi Email Alert Khi Realtime < Total Morning

## Logic Hoạt Động

### 1. Missing Period Tracking (PhaseManager - mỗi 1 phút)
- **PhaseManager** chạy mỗi **1 phút** để kiểm tra `realtime < total_morning`
- Khi phát hiện missing, tạo **missing period** và lưu `start_time`
- Missing period được track liên tục cho đến khi `realtime >= total_morning`

### 2. Alert Check (AlertManager - mỗi 30 phút)
- **AlertManager** chạy mỗi **30 phút** để kiểm tra và gửi email
- Điều kiện gửi email:
  1. ✅ Missing period đã kéo dài **>= 30 phút**
  2. ✅ Lần alert cuối cùng đã cách đây **>= 30 phút** (hoặc chưa có alert nào)

## Timeline Ví Dụ

### Scenario 1: Missing bắt đầu đúng lúc alert check
```
T0 (08:30): realtime < total_morning → Missing period bắt đầu
T0+30 (09:00): Alert check #1
  - Duration = 30 phút ✅
  - Last alert = None ✅
  → 📧 GỬI EMAIL ĐẦU TIÊN

T0+60 (09:30): Alert check #2
  - Duration = 60 phút ✅
  - Last alert = 30 phút trước ✅
  → 📧 GỬI EMAIL THỨ 2

T0+90 (10:00): Alert check #3
  - Duration = 90 phút ✅
  - Last alert = 30 phút trước ✅
  → 📧 GỬI EMAIL THỨ 3

... và cứ thế mỗi 30 phút
```

### Scenario 2: Missing bắt đầu giữa 2 lần alert check
```
T0 (08:45): realtime < total_morning → Missing period bắt đầu
T0+15 (09:00): Alert check #1
  - Duration = 15 phút ❌ (< 30 phút)
  → ⏸️ KHÔNG GỬI (chờ đủ 30 phút)

T0+45 (09:30): Alert check #2
  - Duration = 45 phút ✅ (>= 30 phút)
  - Last alert = None ✅
  → 📧 GỬI EMAIL ĐẦU TIÊN

T0+75 (10:00): Alert check #3
  - Duration = 75 phút ✅
  - Last alert = 30 phút trước ✅
  → 📧 GỬI EMAIL THỨ 2

... và cứ thế mỗi 30 phút
```

### Scenario 3: Missing trong giờ nghỉ trưa (11:55-13:15)
```
T0 (11:00): realtime < total_morning → Missing period bắt đầu
T0+30 (11:30): Alert check #1
  - Duration = 30 phút ✅
  - Last alert = None ✅
  → 📧 GỬI EMAIL ĐẦU TIÊN

T0+55 (11:55): Vào giờ nghỉ trưa
  - Phase = LUNCH_BREAK
  - Alert check bị SKIP (không chạy)

T0+130 (13:15): Ra khỏi giờ nghỉ trưa
  - Phase = AFTERNOON_MONITORING
  - Alert check tiếp tục

T0+130 (13:15): Alert check #2
  - Duration = 130 phút ✅
  - Last alert = 145 phút trước ✅ (> 30 phút)
  → 📧 GỬI EMAIL THỨ 2 (sau giờ nghỉ trưa)

T0+160 (13:45): Alert check #3
  - Duration = 160 phút ✅
  - Last alert = 30 phút trước ✅
  → 📧 GỬI EMAIL THỨ 3

... và cứ thế mỗi 30 phút
```

## Tóm Tắt

### ⏰ Thời điểm gửi email đầu tiên:
- **Sớm nhất**: 30 phút sau khi `realtime < total_morning` bắt đầu
- **Muộn nhất**: 60 phút sau (nếu missing bắt đầu ngay sau alert check)

### 📧 Tần suất gửi email:
- **Email đầu tiên**: Khi missing period >= 30 phút
- **Email tiếp theo**: Mỗi 30 phút một lần (nếu vẫn còn missing)
- **Tối đa**: 2 email/giờ (nếu missing kéo dài)

### ⏸️ Tạm dừng alert:
- **11:55-13:15**: Không gửi alert (giờ nghỉ trưa)
- Sau 13:15: Tiếp tục gửi nếu vẫn còn missing

### ✅ Điều kiện gửi email:
1. `realtime < total_morning` (có missing people)
2. Missing period duration >= 30 phút
3. Lần alert cuối cùng >= 30 phút trước (hoặc chưa có)
4. Đang trong monitoring phase (không phải lunch, không phải morning count)

## Code References

- **PhaseManager**: `app/phase_manager.py` - Track missing periods mỗi 1 phút
- **AlertManager**: `app/alert_manager.py` - Check và gửi alert mỗi 30 phút
- **Alert check interval**: `IntervalTrigger(minutes=30)`
- **Duration check**: `if duration_minutes < 30: return`
- **Spam prevention**: `if time_since_last_alert < 30: return`
