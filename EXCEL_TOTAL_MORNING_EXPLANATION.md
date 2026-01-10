# Giải Thích: Excel Đếm và Tính Total Morning

## 📊 Cách Excel Tính `total_morning`

### 1. **Định Nghĩa `total_morning`**

```
total_morning = (Số người IN - Số người OUT) trong khoảng thời gian 06:00 - 08:30
```

**Công thức:**
```
total_morning = IN_count - OUT_count
```

**Ví dụ:**
- Trong khoảng 06:00-08:30 có:
  - 19 người đi **IN**
  - 13 người đi **OUT**
- → `total_morning = 19 - 13 = 6`

---

## 🔍 Quy Trình Excel Lấy Dữ Liệu

### **Bước 1: Kiểm tra `daily_state` (Ưu tiên cao nhất)**

Excel kiểm tra bảng `daily_state` trong database:

```sql
SELECT total_morning, is_frozen, realtime_in, realtime_out
FROM daily_state
WHERE date = '2026-01-08'
```

**Nếu có `daily_state` và `is_frozen = True`:**
- ✅ **Sử dụng giá trị `total_morning` đã được "đóng băng" (frozen)**
- ✅ Giá trị này được lưu vào lúc **08:30** khi morning phase kết thúc
- ✅ Giá trị này **KHÔNG BAO GIỜ thay đổi** sau khi đã frozen

**Ví dụ:**
- Lúc 08:30, app tính được `total_morning = 6` (IN: 19 - OUT: 13)
- App lưu vào `daily_state` với `is_frozen = True`
- Excel sẽ luôn lấy giá trị `6` này, **KHÔNG tính lại từ events**

---

### **Bước 2: Verify nếu `total_morning = 0`**

Nếu `daily_state.total_morning = 0` nhưng `is_frozen = True`:

**Excel sẽ kiểm tra lại:**
- Tính `total_morning` từ events trong morning phase (06:00-08:30)
- Nếu có events nhưng `total_morning = 0` → Có thể app đã restart
- → Excel sẽ **dùng giá trị tính từ events** thay vì giá trị frozen = 0

**Ví dụ:**
- `daily_state.total_morning = 0` (frozen)
- Nhưng trong events có: IN=19, OUT=13 trong 06:00-08:30
- → Excel tính lại: `total_morning = 19 - 13 = 6`
- → Excel dùng giá trị `6` (không dùng `0`)

---

### **Bước 3: Fallback - Tính từ Events**

Nếu **KHÔNG có `daily_state`** hoặc **`is_frozen = False`**:

**Excel sẽ tính trực tiếp từ bảng `events`:**

```sql
SELECT 
    SUM(CASE WHEN UPPER(direction) = 'IN' THEN 1 ELSE 0 END) as in_count,
    SUM(CASE WHEN UPPER(direction) = 'OUT' THEN 1 ELSE 0 END) as out_count
FROM events
WHERE substr(timestamp, 1, 10) = '2026-01-08'
  AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + 
      CAST(substr(timestamp, 15, 2) AS INTEGER) >= 360  -- 06:00 = 360 phút
  AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + 
      CAST(substr(timestamp, 15, 2) AS INTEGER) < 510   -- 08:30 = 510 phút
```

**Sau đó tính:**
```
total_morning = in_count - out_count
```

---

## 📋 Tóm Tắt Logic

### **Priority 1: `daily_state.total_morning` (nếu `is_frozen = True`)**
```
IF daily_state.exists AND is_frozen = True AND total_morning != 0:
    → Dùng giá trị frozen (chính xác nhất)
```

### **Priority 2: Verify nếu `total_morning = 0`**
```
IF daily_state.total_morning = 0 AND is_frozen = True:
    → Tính lại từ events
    → Nếu có events → Dùng giá trị tính từ events
    → Nếu không có events → Dùng 0
```

### **Priority 3: Tính từ Events (fallback)**
```
IF daily_state không tồn tại HOẶC is_frozen = False:
    → Tính trực tiếp từ events trong 06:00-08:30
    → total_morning = IN_count - OUT_count
```

---

## 🎯 Ví Dụ Cụ Thể

### **Ví dụ 1: Normal Case (App chạy liên tục)**

**Timeline:**
- 06:00: App reset, bắt đầu đếm
- 06:00-08:30: Có 19 IN, 13 OUT
- 08:30: App lưu `total_morning = 6` vào `daily_state` với `is_frozen = True`
- 10:00: Excel export

**Excel làm gì:**
1. Đọc `daily_state` → `total_morning = 6`, `is_frozen = True`
2. ✅ **Dùng giá trị `6`** (không tính lại)

**Kết quả Excel:** `total_morning = 6`

---

### **Ví dụ 2: App Restart (total_morning = 0 trong daily_state)**

**Timeline:**
- 06:00: App reset, bắt đầu đếm
- 06:00-08:30: Có 19 IN, 13 OUT
- 08:30: App lưu `total_morning = 6` vào `daily_state`
- 09:00: **App crash và restart**
- 09:00: App restart, `daily_state.total_morning = 0` (do reset)
- 10:00: Excel export

**Excel làm gì:**
1. Đọc `daily_state` → `total_morning = 0`, `is_frozen = True`
2. ⚠️ Phát hiện `total_morning = 0` nhưng `is_frozen = True`
3. Tính lại từ events: IN=19, OUT=13 → `total_morning = 6`
4. ✅ **Dùng giá trị `6`** (tính từ events)

**Kết quả Excel:** `total_morning = 6` (chính xác)

---

### **Ví dụ 3: Chưa đến 08:30 (is_frozen = False)**

**Timeline:**
- 06:00: App reset, bắt đầu đếm
- 07:00: Excel export (chưa đến 08:30)
- 07:00: Có 10 IN, 5 OUT

**Excel làm gì:**
1. Đọc `daily_state` → `is_frozen = False` (chưa frozen)
2. Tính từ events: IN=10, OUT=5 → `total_morning = 5`
3. ✅ **Dùng giá trị `5`** (tính từ events)

**Kết quả Excel:** `total_morning = 5`

---

## 📝 Code Tham Khảo

### **File: `export/db_queries.py`**

```python
def get_total_morning(cursor, target_date, morning_start, morning_end):
    """
    Calculate TOTAL MORNING: Net number of people during morning phase (IN - OUT).
    
    Definition: total_morning = (IN events - OUT events) during morning_start and morning_end.
    """
    # Query events trong khoảng 06:00-08:30
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN UPPER(direction) = 'IN' THEN 1 ELSE 0 END) as in_count,
            SUM(CASE WHEN UPPER(direction) = 'OUT' THEN 1 ELSE 0 END) as out_count
        FROM events
        WHERE substr(timestamp, 1, 10) = ?
          AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + 
              CAST(substr(timestamp, 15, 2) AS INTEGER) >= ?
          AND CAST(substr(timestamp, 12, 2) AS INTEGER) * 60 + 
              CAST(substr(timestamp, 15, 2) AS INTEGER) < ?
    """, (target_date, start_minutes, end_minutes))
    
    in_count = result[0] or 0
    out_count = result[1] or 0
    total_morning = in_count - out_count  # IN - OUT
    
    return total_morning
```

### **File: `export/db_queries.py` - `get_all_data_for_date()`**

```python
def get_all_data_for_date(cursor, target_date, morning_start, morning_end):
    """
    Get all data for Excel export.
    
    CRITICAL: total_morning must be taken from daily_state (frozen value) if available.
    """
    # Priority 1: Get from daily_state (frozen value)
    daily_state = get_daily_state(cursor, target_date)
    
    if daily_state and daily_state.get('is_frozen') and daily_state.get('total_morning') is not None:
        total_morning_frozen = daily_state['total_morning']
        
        # Verify: If total_morning=0 but there are events, recalculate
        if total_morning_frozen == 0:
            total_morning_from_events = get_total_morning(cursor, target_date, morning_start, morning_end)
            if total_morning_from_events > 0:
                # Use calculated value (app may have restarted)
                total_morning = total_morning_from_events
            else:
                total_morning = 0
        else:
            # Use frozen value (non-zero)
            total_morning = total_morning_frozen
    else:
        # Fallback: Calculate from events
        total_morning = get_total_morning(cursor, target_date, morning_start, morning_end)
    
    return {
        'total_morning': total_morning,
        # ... other data
    }
```

---

## ✅ Kết Luận

1. **Excel ưu tiên dùng giá trị frozen** từ `daily_state` (chính xác nhất)
2. **Nếu `total_morning = 0` nhưng có events** → Excel tính lại từ events
3. **Nếu chưa frozen** → Excel tính trực tiếp từ events
4. **Công thức luôn là:** `total_morning = IN_count - OUT_count` (trong 06:00-08:30)

**Đảm bảo:**
- ✅ Excel luôn có giá trị chính xác
- ✅ Xử lý được trường hợp app restart
- ✅ Dữ liệu lấy trực tiếp từ database (không phụ thuộc memory)
