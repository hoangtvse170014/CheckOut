# Tạo File Excel Mới Hằng Ngày

## ✅ Đã Cấu Hình

### 1. **Tạo File Excel Mới vào 06:00 (Daily Reset)**
- ✅ Khi daily reset xảy ra lúc **06:00**, hệ thống tự động tạo file Excel mới cho ngày hôm nay
- ✅ File được tạo với tên: `people_counter_YYYY-MM-DD.xlsx` (ví dụ: `people_counter_2026-01-09.xlsx`)
- ✅ File được tạo ngay sau khi reset dữ liệu, đảm bảo mỗi ngày có file riêng

### 2. **Cập Nhật File Excel Mỗi 30 Phút**
- ✅ File Excel được cập nhật mỗi 30 phút trong suốt ngày
- ✅ Dữ liệu được lấy trực tiếp từ database (không phụ thuộc vào memory)
- ✅ File được ghi đè an toàn (atomic write: temp file → rename)

### 3. **Finalize File Ngày Hôm Trước**
- ✅ Vào lúc **06:00**, hệ thống finalize file của ngày hôm trước (nếu chưa có)
- ✅ Vào lúc **00:00** (midnight), hệ thống cũng kiểm tra và finalize file ngày hôm trước (backup)

## 📁 Cấu Trúc File

```
exports/
└── daily/
    ├── people_counter_2026-01-08.xlsx  (Ngày hôm qua - đã finalize)
    ├── people_counter_2026-01-09.xlsx  (Ngày hôm nay - đang cập nhật)
    └── people_counter_2026-01-09.tmp.xlsx  (File tạm khi đang tạo)
```

## 🔄 Quy Trình Tự Động

### Lúc 06:00 (Daily Reset):
1. ✅ Reset tất cả dữ liệu
2. ✅ Tạo file Excel mới cho ngày hôm nay: `people_counter_2026-01-09.xlsx`
3. ✅ Finalize file ngày hôm qua (nếu chưa có)
4. ✅ Export rolling summary (7 ngày)
5. ✅ Cleanup files cũ (> 5 ngày)

### Trong Ngày (Mỗi 30 Phút):
1. ✅ Cập nhật file Excel của ngày hôm nay
2. ✅ Ghi đè file với dữ liệu mới nhất từ database

### Lúc 00:00 (Midnight - Backup):
1. ✅ Kiểm tra và finalize file ngày hôm trước (nếu chưa có)
2. ✅ Export rolling summary

## 📊 Nội Dung File Excel

Mỗi file Excel chứa 4 sheets:

### Sheet 1: **SUMMARY**
- Date
- Total Morning
- Current Realtime
- Current Missing
- Last Updated Time

### Sheet 2: **MISSING_PERIODS**
- Start Time
- End Time
- Duration (minutes)
- Missing Count
- Session

### Sheet 3: **ALERTS**
- Alert Time
- Total Morning
- Realtime Count
- Missing Count
- Notification Status

### Sheet 4: **EVENTS**
- Event Time
- Direction (IN/OUT)
- Camera ID
- Track ID

## 🎯 Đảm Bảo

- ✅ **Mỗi ngày có file riêng**: Tên file chứa ngày tháng (`YYYY-MM-DD`)
- ✅ **File được tạo ngay khi bắt đầu ngày mới**: Lúc 06:00 khi daily reset
- ✅ **File được cập nhật liên tục**: Mỗi 30 phút trong suốt ngày
- ✅ **Dữ liệu chính xác**: Lấy trực tiếp từ database, không phụ thuộc memory
- ✅ **Atomic write**: Sử dụng temp file → rename để tránh corruption
- ✅ **Tự động cleanup**: Xóa files cũ hơn 5 ngày

## 📝 Lưu ý

- File Excel có thể bị mở trong Excel → hệ thống sẽ bỏ qua export (không ghi đè)
- Nếu file đang mở, bạn cần đóng file trước khi export tiếp theo
- File tạm (`.tmp.xlsx`) sẽ được tự động xóa sau khi export thành công
