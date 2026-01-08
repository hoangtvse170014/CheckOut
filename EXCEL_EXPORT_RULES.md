# Quy Tắc Tạo Excel Export

## Tổng Quan

Hệ thống tự động tạo file Excel để báo cáo dữ liệu đếm người. Excel được tạo bởi `ExcelExportScheduler` chạy trong background thread.

## Cấu Trúc Thư Mục

```
exports/
├── daily/              # File Excel hàng ngày
│   ├── people_counter_2026-01-08.xlsx
│   └── people_counter_2026-01-08.tmp.xlsx  # File tạm khi đang tạo
└── summary/            # File tổng hợp (rolling summary)
    └── people_counter_summary_7days.xlsx
```

## Quy Tắc Tạo Excel

### 1. **Daily Excel (File Hàng Ngày)**

**Tên file:** `people_counter_YYYY-MM-DD.xlsx` (ví dụ: `people_counter_2026-01-08.xlsx`)

**Thời điểm tạo:**
- **Ngay khi khởi động app** (startup export)
- **Mỗi 30 phút** (interval export)
- **Lúc 00:00** (finalize file của ngày hôm trước)
- **Khi app shutdown** (force final export)

**Cơ chế tạo file:**
1. Tạo file tạm: `people_counter_YYYY-MM-DD.tmp.xlsx`
2. Ghi dữ liệu vào file tạm
3. Xóa file cũ (nếu có)
4. Đổi tên file tạm thành file chính thức
5. Nếu file đang mở trong Excel → bỏ qua export (không ghi đè)

**Nội dung file (3 sheets):**

#### Sheet 1: **SUMMARY**
| Field | Value |
|-------|-------|
| Date | 2026-01-08 |
| Total Morning | 6 (số người vào buổi sáng) |
| Missing Periods | "14:30 (-2), 15:00 (-2)" (các khoảng thời gian thiếu người) |
| Last Updated | 2026-01-08 15:07:03 |

#### Sheet 2: **ALERTS**
| Time Window | Expected | Current | Missing |
|-------------|----------|---------|---------|
| 2026-01-08 14:30:00 | 6 | 4 | 2 |
| 2026-01-08 15:00:00 | 6 | 4 | 2 |

**Dữ liệu lấy từ:** Bảng `alert_logs` trong database

#### Sheet 3: **EVENTS**
| Time | Direction | Camera |
|------|-----------|--------|
| 2026-01-08 08:15:23 | IN | camera_01 |
| 2026-01-08 08:20:45 | OUT | camera_01 |
| 2026-01-08 14:30:12 | IN | camera_01 |

**Dữ liệu lấy từ:** Bảng `people_events` trong database

**Formatting:**
- Header row: Nền xanh (#366092), chữ trắng, in đậm
- Freeze header row (dòng 1 luôn hiển thị)
- Auto-filter enabled
- Auto-adjust column width (max 50 characters)

### 2. **Rolling Summary Excel (Tổng Hợp)**

**Tên file:** `people_counter_summary_7days.xlsx`

**Thời điểm tạo:**
- **Ngay khi khởi động app** (startup export)
- **Mỗi 30 phút** (cùng lúc với daily export)
- **Lúc 00:00** (cùng lúc với daily export)

**Nội dung:**
- Tổng hợp dữ liệu từ **7 ngày gần nhất**
- Lấy từ các file daily Excel đã tạo
- Tạo file mới trong thư mục `exports/summary/`

## Cơ Chế Hoạt Động

### Background Thread

`ExcelExportScheduler` chạy trong background thread riêng, không block main loop:

```python
# Interval: 30 phút
_export_interval_seconds = 30 * 60  # 30 minutes

# Scheduler loop chạy mỗi 1 phút để check
while self._running:
    # Check nếu đã qua 30 phút → export
    if elapsed >= self._export_interval_seconds:
        self._export_daily_excel(today, output_file)
        self._export_rolling_summary()
    
    time.sleep(60)  # Sleep 1 phút
```

### Database Query

**Daily Summary:**
```sql
SELECT date, total_morning, updated_at
FROM daily_summary
WHERE date = '2026-01-08'
```

**Alerts:**
```sql
SELECT alert_time, expected_total, current_total, missing
FROM alert_logs
WHERE date(alert_time) = '2026-01-08'
ORDER BY alert_time ASC
```

**Events:**
```sql
SELECT event_time, direction, camera_id
FROM people_events
WHERE date(event_time) = '2026-01-08'
ORDER BY event_time ASC
```

### Atomic File Writing

Để tránh file bị corrupt khi đang ghi:

1. **Tạo file tạm:** `people_counter_2026-01-08.tmp.xlsx`
2. **Ghi dữ liệu** vào file tạm
3. **Kiểm tra file cũ:**
   - Nếu file cũ tồn tại → thử xóa
   - Nếu file đang mở trong Excel → bỏ qua export (không ghi đè)
4. **Rename file tạm** thành file chính thức (atomic operation)

### Error Handling

- **File đang mở:** Bỏ qua export, không crash app
- **Database error:** Log error, tiếp tục chạy
- **Permission error:** Bỏ qua export, log warning
- **Import error (pandas/openpyxl):** Log error, return False

## Cleanup (Dọn Dẹp)

**Thời điểm:** Lúc 00:00 mỗi ngày

**Quy tắc:**
- Xóa các file Excel **cũ hơn 5 ngày** trong thư mục `exports/daily/`
- Giữ lại file của 5 ngày gần nhất

**Ví dụ:**
- Hôm nay: 2026-01-08
- Cutoff date: 2026-01-03
- Xóa: `people_counter_2026-01-02.xlsx`, `people_counter_2026-01-01.xlsx`, ...
- Giữ: `people_counter_2026-01-03.xlsx` đến `people_counter_2026-01-08.xlsx`

## Dependencies

**Required libraries:**
- `pandas` - Để tạo DataFrame và ghi Excel
- `openpyxl` - Engine để ghi file Excel (.xlsx)

**Nếu thiếu:**
- App vẫn chạy bình thường
- Excel export sẽ fail và log error
- Không ảnh hưởng đến main app

## Log Messages

**Thành công:**
```
Excel export completed: people_counter_2026-01-08.xlsx (150 events, 3 alerts)
```

**File đang mở:**
```
Cannot overwrite people_counter_2026-01-08.xlsx - file may be open in Excel. Skipping export.
```

**Cleanup:**
```
Cleanup completed: Deleted 2 old file(s): people_counter_2026-01-01.xlsx, people_counter_2026-01-02.xlsx
```

## Tóm Tắt

| Thông số | Giá trị |
|----------|---------|
| **Interval export** | 30 phút |
| **Startup export** | Có (ngay khi khởi động) |
| **Midnight export** | Có (00:00) |
| **Shutdown export** | Có (force final) |
| **File format** | .xlsx (Excel 2007+) |
| **Sheets** | 3 (SUMMARY, ALERTS, EVENTS) |
| **Rolling summary** | 7 ngày |
| **Cleanup** | Xóa file > 5 ngày |
| **Thread-safe** | Có (background thread) |
| **Atomic write** | Có (temp file → rename) |
