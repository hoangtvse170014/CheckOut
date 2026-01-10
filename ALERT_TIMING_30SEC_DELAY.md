# Logic Gửi Mail: 30 Giây Delay + 30 Phút

## Yêu Cầu

- **Gửi mail sau 30 phút thiếu người**
- **Thời gian bắt đầu đếm phút là ngay sau khi phát hiện thiếu người 30 giây**

## Logic Mới

### Timeline

```
T0: Phát hiện thiếu người → Missing period bắt đầu (start_time = T0)
T0 + 30 giây: Bắt đầu đếm phút (count_start_time = T0 + 30s)
T0 + 30.5 phút: Gửi mail đầu tiên (30 giây delay + 30 phút)
```

### Công Thức

```
Alert được gửi khi:
  duration >= 30.5 phút (từ start_time)
  = 30 giây delay + 30 phút đếm
```

## Ví Dụ

### Scenario 1: Missing bắt đầu lúc 08:30:00

```
08:30:00 - Phát hiện thiếu người → Missing period start
08:30:30 - Bắt đầu đếm (30 giây sau)
09:01:00 - Gửi mail đầu tiên (30.5 phút từ 08:30:00)
09:31:00 - Gửi mail thứ 2 (30 phút sau mail đầu)
10:01:00 - Gửi mail thứ 3 (30 phút sau mail thứ 2)
```

### Scenario 2: Missing bắt đầu lúc 08:45:15

```
08:45:15 - Phát hiện thiếu người → Missing period start
08:45:45 - Bắt đầu đếm (30 giây sau)
09:16:15 - Gửi mail đầu tiên (30.5 phút từ 08:45:15)
09:46:15 - Gửi mail thứ 2 (30 phút sau mail đầu)
```

## Code Changes

### File: `app/alert_manager.py`

```python
# Send alert if duration >= 30.5 minutes (30 seconds delay + 30 minutes)
ALERT_DELAY_SECONDS = 30  # 30 giây delay trước khi bắt đầu đếm
ALERT_DURATION_MINUTES = 30  # 30 phút sau khi bắt đầu đếm
ALERT_TOTAL_MINUTES = ALERT_DURATION_MINUTES + (ALERT_DELAY_SECONDS / 60)  # 30.5 phút

if duration_minutes < ALERT_TOTAL_MINUTES:
    # Chưa đủ thời gian, không gửi mail
    return
```

## Lợi Ích

1. **Tránh false positive**: 30 giây delay cho phép hệ thống xác nhận missing period thực sự
2. **Chính xác hơn**: Đếm từ 30 giây sau khi phát hiện, không phải ngay lập tức
3. **Rõ ràng**: Timeline rõ ràng: 30s delay → 30 min đếm → gửi mail

## Recurring Alerts

Sau khi gửi mail đầu tiên:
- Mỗi 30 phút gửi lại nếu vẫn còn thiếu người
- Không có delay 30 giây cho các alert tiếp theo (chỉ áp dụng cho alert đầu tiên)
