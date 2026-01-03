# Quick Start Guide

Hướng dẫn nhanh để chạy People Counter MVP.

## Bước 1: Cài đặt Dependencies

```bash
pip install -r requirements.txt
```

## Bước 2: Cấu hình

Copy file `env.example` thành `.env`:

```bash
# Windows
copy env.example .env

# Linux/Mac
cp env.example .env
```

Chỉnh sửa `.env` với thông tin camera của bạn:

```env
# USB Camera (index 0, 1, 2...)
CAMERA__URL=0

# Hoặc RTSP Stream
# CAMERA__URL=rtsp://username:password@192.168.1.100:554/stream1

# Đường line để đếm (tọa độ trong frame)
# Xác định bằng cách chạy test_camera.py và click vào frame
LINE__LINE_START=0,240
LINE__LINE_END=640,240

# Model (yolov8n.pt cho CPU, yolov8s.pt cho GPU)
DETECTION__MODEL_NAME=yolov8n.pt
DETECTION__DEVICE=cpu

# FPS cap (giảm nếu CPU yếu)
CAMERA__FPS_CAP=10
```

## Bước 3: Kiểm tra Setup

```bash
python scripts/check_setup.py
```

## Bước 4: Test Camera

```bash
python scripts/test_camera.py
```

Nhấn 'q' để thoát. Kiểm tra xem camera có hoạt động không.

## Bước 5: Xác định Tọa độ Line

Có 2 cách:

### Cách 1: Dùng test_camera.py

1. Chạy `python scripts/test_camera.py`
2. Xem frame và ước lượng tọa độ line
3. Cập nhật `LINE__LINE_START` và `LINE__LINE_END` trong `.env`

### Cách 2: Dùng demo với video

1. Có video mẫu với người đi qua cửa
2. Chạy: `python scripts/demo_video.py video.mp4 --fps 10`
3. Xem overlay và điều chỉnh line cho đúng

## Bước 6: Chạy Ứng dụng

```bash
python scripts/run.py
```

Ứng dụng sẽ:
- Kết nối camera
- Detect và track người
- Đếm số người qua line
- Lưu events vào database
- Tự động aggregate theo window A/B
- Gửi alert nếu OUT_A > IN_B

## Bước 7: Xem Kết quả

### Xem Logs

Logs được ghi vào `people_counter.log` và console.

### Xem Database

Dùng SQLite browser hoặc command line:

```bash
sqlite3 people_counter.db

# Xem events
SELECT * FROM events ORDER BY timestamp DESC LIMIT 10;

# Xem aggregations
SELECT * FROM aggregations;

# Xem alerts
SELECT * FROM alerts;
```

### Xem Snapshots

Nếu `SAVE_SNAPSHOTS=true`, snapshots được lưu trong thư mục `snapshots/`.

## Troubleshooting

### Camera không kết nối

- **USB Camera**: Thử index khác (0, 1, 2...)
- **RTSP**: Test với VLC player trước, kiểm tra URL format

### FPS thấp

- Giảm `CAMERA__FPS_CAP` xuống 5-8
- Dùng `yolov8n.pt` thay vì model lớn hơn
- Kiểm tra CPU usage

### Đếm sai

- Kiểm tra line position với `demo_video.py`
- Tăng `LINE__MIN_TRACK_LENGTH` (mặc định: 5)
- Tăng `LINE__COOLDOWN_FRAMES` (mặc định: 30)
- Điều chỉnh `DETECTION__CONF_THRESHOLD`

## Next Steps

- Đọc `README.md` để biết chi tiết về tuning và configuration
- Cấu hình notification (Telegram/Email/Webhook) trong `.env`
- Tùy chỉnh time windows trong `.env`

