# Hướng dẫn chạy tự động 24/7

## ✅ Đã cấu hình

### 1. **Alert System (Gửi mail sau 30 phút)**
- ✅ Alert check chạy mỗi **30 phút** (thay vì 1 phút)
- ✅ Chỉ gửi mail khi **duration >= 30 phút** từ khi vắng
- ✅ Recurring alerts mỗi 30 phút nếu vẫn còn thiếu người

### 2. **Daily Reset Tự động**
- ✅ **06:00**: Tự động reset tất cả dữ liệu, bắt đầu đếm TOTAL_MORNING
- ✅ **08:30**: Tự động lock TOTAL_MORNING (is_frozen=True)
- ✅ **23:59**: Tự động đóng các missing periods còn mở, chuẩn bị cho ngày mới

### 3. **Phase Transitions Tự động**
- ✅ **06:00-08:30**: MORNING_COUNT (đếm TOTAL_MORNING)
- ✅ **08:30-11:55**: REALTIME_MORNING (monitoring)
- ✅ **11:55-13:15**: LUNCH_BREAK (tạm dừng alerts)
- ✅ **13:15-23:59**: AFTERNOON_MONITORING (resume alerts)

### 4. **Excel Export Tự động**
- ✅ Export mỗi 30 phút
- ✅ Tự động cleanup files cũ (> 5 ngày)

## 🚀 Cách chạy 24/7

### Option 1: Chạy với Auto-Restart (Khuyến nghị)
```batch
run_24_7.bat
```
- Tự động restart nếu app crash
- Chạy liên tục cho đến khi bạn dừng (Ctrl+C)

### Option 2: Chạy thông thường
```batch
python scripts/run.py
```
- Chạy một lần, nếu crash thì dừng

### Option 3: Chạy như Windows Service (Nâng cao)
- Sử dụng NSSM (Non-Sucking Service Manager) hoặc Task Scheduler
- Đảm bảo app tự động start khi Windows khởi động

## 📋 Checklist trước khi chạy 24/7

- [ ] Camera đã kết nối và hoạt động
- [ ] Database (`data/people_counter.db`) có quyền ghi
- [ ] Email config đã đúng (`.env` file)
- [ ] Thư mục `exports/` có quyền ghi
- [ ] Windows Firewall cho phép port 8000 (nếu dùng dashboard)
- [ ] PC không tự động sleep/hibernate

## ⚙️ Cấu hình trong `.env`

```env
# Timezone
WINDOW__TIMEZONE=Asia/Ho_Chi_Minh

# Reset time (06:00)
WINDOW__RESET_TIME=06:00

# Email (cho alerts)
EMAIL__SMTP_HOST=smtp.gmail.com
EMAIL__SMTP_PORT=587
EMAIL__FROM_EMAIL=your-email@gmail.com
EMAIL__FROM_PASSWORD=your-app-password
EMAIL__TO_EMAILS=alert1@example.com,alert2@example.com
```

## 🔍 Kiểm tra hoạt động

### 1. Kiểm tra Daily Reset
- Xem log file `people_counter.log` vào lúc 06:00
- Tìm dòng: `=== DAILY RESET AT 06:00 ===`

### 2. Kiểm tra Alert
- Xem log file vào lúc có missing period >= 30 phút
- Tìm dòng: `Sending alert for missing period`

### 3. Kiểm tra Excel Export
- Kiểm tra thư mục `exports/daily/`
- File mới nhất phải có timestamp gần đây

## 🛠️ Troubleshooting

### App crash liên tục
1. Kiểm tra log file `people_counter.log`
2. Kiểm tra camera connection
3. Kiểm tra database permissions

### Không nhận được email
1. Kiểm tra email config trong `.env`
2. Kiểm tra Gmail App Password (không dùng mật khẩu thường)
3. Kiểm tra log: `Error sending email`

### Daily reset không chạy
1. Kiểm tra timezone trong `.env`
2. Kiểm tra system time của PC
3. Xem log vào lúc 06:00

## 📝 Lưu ý

- **App sẽ tự động reset vào 06:00 mỗi ngày**
- **TOTAL_MORNING sẽ được lock vào 08:30**
- **Alerts chỉ gửi sau 30 phút từ khi vắng**
- **App có thể chạy 24/7 không cần can thiệp**

## 🎯 Ngày mai (09/01/2026)

Hệ thống sẽ tự động:
1. ✅ Reset tất cả dữ liệu lúc **06:00**
2. ✅ Bắt đầu đếm TOTAL_MORNING từ **06:00-08:30**
3. ✅ Lock TOTAL_MORNING lúc **08:30**
4. ✅ Chuyển sang REALTIME monitoring
5. ✅ Gửi alert nếu thiếu người >= 30 phút
6. ✅ Export Excel mỗi 30 phút

**Bạn chỉ cần chạy `run_24_7.bat` và để app chạy tự động!**
