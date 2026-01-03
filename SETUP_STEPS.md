# Hướng dẫn Setup từng bước

## Thứ tự chạy lệnh

### Bước 1: Cài đặt Dependencies

```bash
pip install -r requirements.txt
```

**Lưu ý:** 
- Lần đầu có thể mất vài phút để download YOLO model
- Nếu có GPU, có thể cài thêm `torch` với CUDA support

---

### Bước 2: Tạo file cấu hình

**Windows:**
```bash
copy env.example .env
```

**Linux/Mac:**
```bash
cp env.example .env
```

---

### Bước 3: Chỉnh sửa file .env

Mở file `.env` và chỉnh sửa các thông tin sau:

**Bắt buộc:**
- `CAMERA__URL` - URL camera của bạn
  - USB camera: `0`, `1`, `2`...
  - RTSP: `rtsp://username:password@ip:port/stream`

**Quan trọng:**
- `LINE__LINE_START` và `LINE__LINE_END` - Tọa độ đường line
  - Mặc định: `0,240` và `640,240` (giữa frame 640x480)
  - Sẽ cần điều chỉnh sau khi test camera

**Tùy chọn:**
- `DETECTION__MODEL_NAME` - Model YOLO (mặc định `yolov8n.pt` cho CPU)
- `CAMERA__FPS_CAP` - FPS cap (mặc định 10)
- `NOTIFICATION__ENABLED` - Bật/tắt notification

---

### Bước 4: Kiểm tra Setup

```bash
python scripts/check_setup.py
```

**Kết quả mong đợi:**
- ✓ Tất cả packages đã cài đặt
- ✓ YOLO model có thể load
- ✓ Tracker có thể khởi tạo
- ⚠ Có thể có warning về config file (bình thường nếu chưa tạo .env)

**Nếu có lỗi:**
- Kiểm tra lại bước 1 (cài đặt dependencies)
- Đảm bảo Python version >= 3.11

---

### Bước 5: Test Camera

```bash
python scripts/test_camera.py
```

**Mục đích:**
- Kiểm tra camera có kết nối được không
- Xem FPS thực tế
- Xác định resolution của frame

**Thao tác:**
- Nhấn `q` để thoát
- Quan sát FPS và resolution để điều chỉnh config

**Nếu không kết nối được:**
- USB camera: Thử index khác (0, 1, 2...)
- RTSP: Test với VLC player trước, kiểm tra URL format

---

### Bước 6: Xác định tọa độ Line (Quan trọng!)

Có 2 cách:

#### Cách 1: Ước lượng từ test_camera.py

Khi chạy `test_camera.py`, quan sát frame và ước lượng:
- Line nên đặt ở giữa cửa, vuông góc với hướng di chuyển
- Ghi lại tọa độ (x1, y1) và (x2, y2)
- Cập nhật trong `.env`:
  ```
  LINE__LINE_START=x1,y1
  LINE__LINE_END=x2,y2
  ```

#### Cách 2: Dùng demo với video (Khuyến nghị)

Nếu có video mẫu:
```bash
python scripts/demo_video.py path/to/video.mp4 --fps 10
```

- Video sẽ hiển thị overlay với line
- Line được vẽ màu xanh
- Tracks được vẽ với bounding box và ID
- Nhấn `r` để reset counts
- Nhấn `q` để thoát

**Điều chỉnh line:**
- Sửa `LINE__LINE_START` và `LINE__LINE_END` trong `.env`
- Chạy lại demo cho đến khi line đúng vị trí

---

### Bước 7: Chạy ứng dụng chính

```bash
python scripts/run.py
```

**Ứng dụng sẽ:**
- Kết nối camera
- Bắt đầu detect và track
- Đếm số người qua line
- Lưu events vào database
- Tự động chạy scheduler cho windows A/B
- Gửi alert nếu OUT_A > IN_B

**Quan sát:**
- Logs hiển thị trên console
- Logs cũng được ghi vào `people_counter.log`
- Metrics được log mỗi phút

**Dừng ứng dụng:**
- Nhấn `Ctrl+C` để dừng gracefully

---

## Tóm tắt thứ tự

```
1. pip install -r requirements.txt
2. copy env.example .env  (hoặc cp env.example .env)
3. [Chỉnh sửa .env với thông tin camera]
4. python scripts/check_setup.py
5. python scripts/test_camera.py
6. [Xác định tọa độ line và cập nhật .env]
7. [Optional] python scripts/demo_video.py video.mp4 --fps 10
8. python scripts/run.py
```

---

## Troubleshooting nhanh

### Lỗi "Module not found"
→ Chạy lại: `pip install -r requirements.txt`

### Camera không kết nối
→ Kiểm tra `CAMERA__URL` trong `.env`, thử index khác

### FPS quá thấp
→ Giảm `CAMERA__FPS_CAP` xuống 5-8 trong `.env`

### Đếm sai
→ Điều chỉnh line position và tăng `LINE__MIN_TRACK_LENGTH`, `LINE__COOLDOWN_FRAMES`

### YOLO model không load
→ Model sẽ tự động download lần đầu, cần internet connection

---

## Sau khi chạy thành công

### Xem kết quả trong database:

```bash
# Windows (cần cài sqlite3 hoặc dùng Python)
python -c "import sqlite3; conn = sqlite3.connect('people_counter.db'); cursor = conn.cursor(); cursor.execute('SELECT * FROM events ORDER BY timestamp DESC LIMIT 10'); print(cursor.fetchall())"

# Linux/Mac
sqlite3 people_counter.db "SELECT * FROM events ORDER BY timestamp DESC LIMIT 10;"
```

### Xem logs:

```bash
# Windows
type people_counter.log

# Linux/Mac
tail -f people_counter.log
```

### Xem snapshots:

Nếu `SAVE_SNAPSHOTS=true`, snapshots được lưu trong thư mục `snapshots/`

