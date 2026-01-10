# Logic Gửi Mail Alert - Final Version

## Yêu Cầu

1. **Missing period chỉ đóng khi missing = 0**
2. **Nếu missing > 0, missing period vẫn tiếp tục đếm thời gian (không reset)**
3. **Khi đủ 30.5 phút (30s delay + 30 min), CHẮC CHẮN gửi mail với số lượng missing tại thời điểm đó**
4. **Không gửi mail khi missing giảm, nhưng vẫn tiếp tục đếm để gửi mail sau 30.5 phút**

## Timeline Ví Dụ

### Scenario 1: Missing giảm nhưng vẫn > 0

```
08:30:00 - Phát hiện thiếu 3 người → Missing period bắt đầu
08:30:30 - Bắt đầu đếm (30 giây sau)
08:55:00 - Missing giảm xuống 2 người (sau 25 phút)
  → Missing period VẪN ACTIVE (vì missing > 0)
  → Thời gian đếm VẪN TIẾP TỤC (không reset)
  → KHÔNG gửi mail (vì chưa đủ 30.5 phút)
09:01:00 - Đủ 30.5 phút (từ 08:30:00)
  → CHẮC CHẮN gửi mail với missing = 2 (số lượng tại thời điểm 09:01:00)
```

### Scenario 2: Missing giảm về 0

```
08:30:00 - Phát hiện thiếu 3 người → Missing period bắt đầu
08:30:30 - Bắt đầu đếm (30 giây sau)
08:55:00 - Missing giảm xuống 0 người (sau 25 phút)
  → Missing period ĐÓNG (vì missing = 0)
  → KHÔNG gửi mail
```

### Scenario 3: Missing thay đổi trong thời gian đếm

```
08:30:00 - Phát hiện thiếu 3 người → Missing period bắt đầu
08:30:30 - Bắt đầu đếm (30 giây sau)
08:45:00 - Missing tăng lên 4 người (sau 15 phút)
  → Missing period VẪN ACTIVE
  → Thời gian đếm VẪN TIẾP TỤC
08:50:00 - Missing giảm xuống 2 người (sau 20 phút)
  → Missing period VẪN ACTIVE (vì missing > 0)
  → Thời gian đếm VẪN TIẾP TỤC
09:01:00 - Đủ 30.5 phút (từ 08:30:00)
  → CHẮC CHẮN gửi mail với missing = 2 (số lượng tại thời điểm 09:01:00)
```

## Logic Code

### 1. Missing Period Management (PhaseManager)

```python
if missing_count > 0:
    # Missing period VẪN ACTIVE
    # Thời gian đếm TIẾP TỤC (không reset)
else:
    # Missing = 0 → ĐÓNG missing period
    self.storage.close_missing_period(period_id, now)
```

### 2. Alert Check Logic (AlertManager)

```python
# Kiểm tra duration >= 30.5 phút
if duration_minutes < 30.5:
    return  # Chưa đủ thời gian

# Nếu missing > 0 và đủ 30.5 phút → CHẮC CHẮN gửi mail
if missing_count > 0:
    # Gửi mail với missing count tại thời điểm hiện tại
    send_alert(missing_count)
```

### 3. Recurring Alerts

- **Cooldown 30 phút**: Nếu alert vừa gửi < 30 phút và missing count không đổi → Skip
- **Missing thay đổi**: Nếu missing count thay đổi (tăng hoặc giảm), vẫn tiếp tục đếm để gửi mail sau 30.5 phút
- **Sau 30 phút**: Gửi recurring alert với missing count hiện tại

## Kết Luận

✅ **Missing period chỉ đóng khi missing = 0**
✅ **Missing > 0 → tiếp tục đếm, không reset**
✅ **Đủ 30.5 phút → CHẮC CHẮN gửi mail với missing tại thời điểm đó**
✅ **Missing giảm nhưng vẫn > 0 → không gửi mail ngay, nhưng vẫn tiếp tục đếm**
