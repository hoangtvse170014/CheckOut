# People Counter MVP

Hệ thống đếm số người ra/vào cửa bằng camera với YOLO detection và ByteTrack tracking.

## Mục tiêu

- Đếm số người đi qua cửa theo 2 hướng: **IN** và **OUT**
- Báo cáo theo khung thời gian:
  - Window A (12:00-12:59): Tổng OUT
  - Window B (13:00-13:59): Tổng IN
- Gửi thông báo khi OUT_A > IN_B

## Cài đặt

### Yêu cầu

- Python 3.11+
- Camera (RTSP stream hoặc USB camera)

### Cài đặt dependencies

```bash
pip install -r requirements.txt
```

### Cấu hình

1. Copy file `.env.example` thành `.env`:
```bash
cp .env.example .env
```

2. Chỉnh sửa `.env` với thông tin của bạn:

```env
# Camera URL (RTSP hoặc USB camera index)
CAMERA__URL=0  # hoặc "rtsp://user:pass@ip:port/stream"

# Đường line để đếm (tọa độ trong frame)
LINE__LINE_START=0,240
LINE__LINE_END=640,240

# Model YOLO (yolov8n.pt cho CPU, yolov8s.pt cho GPU)
DETECTION__MODEL_NAME=yolov8n.pt
DETECTION__DEVICE=cpu

# FPS cap (giảm để tiết kiệm CPU)
CAMERA__FPS_CAP=10

# Notification (nếu cần)
NOTIFICATION__ENABLED=false
NOTIFICATION__CHANNEL=telegram
NOTIFICATION__TELEGRAM_BOT_TOKEN=your_token
NOTIFICATION__TELEGRAM_CHAT_ID=your_chat_id
```

## Kiểm tra Setup

Trước khi chạy, kiểm tra xem mọi thứ đã được cài đặt đúng chưa:

```bash
python scripts/check_setup.py
```

Script này sẽ kiểm tra:
- Tất cả dependencies đã được cài đặt
- Configuration file tồn tại
- YOLO model có thể load
- Tracker có thể khởi tạo

## Chạy

### Chạy ứng dụng chính

```bash
python scripts/run.py
```

Hoặc:

```bash
python -m app.main
```

### Test camera

```bash
python scripts/test_camera.py
```

### Demo với video file

```bash
python scripts/demo_video.py path/to/video.mp4 --fps 10
```

## Cấu trúc thư mục

```
.
├── app/
│   ├── __init__.py
│   ├── config.py          # Cấu hình (Pydantic)
│   ├── camera.py          # Camera stream với reconnect
│   ├── detector.py        # YOLO person detection
│   ├── tracker.py         # ByteTrack/DeepSORT tracking
│   ├── line_counter.py    # Line crossing logic
│   ├── storage.py         # SQLite database
│   ├── scheduler.py       # Time window & alert scheduler
│   ├── notifier.py        # Telegram/Email/Webhook
│   └── main.py            # Main application
├── scripts/
│   ├── run.py             # Run main app
│   ├── test_camera.py     # Test camera connection
│   └── demo_video.py      # Demo với video file
├── requirements.txt
├── .env.example
└── README.md
```

## Tuning Guide

### Model Selection

**CPU (không có GPU):**
- `yolov8n.pt` (nano) - nhanh nhất, độ chính xác thấp hơn
- `yolov8s.pt` (small) - cân bằng tốt

**GPU:**
- `yolov8m.pt` (medium) - tốt hơn
- `yolov8l.pt` (large) - tốt nhất nhưng chậm

**Khuyến nghị:**
- CPU: `yolov8n.pt` với `FPS_CAP=5-10`
- GPU: `yolov8s.pt` hoặc `yolov8m.pt` với `FPS_CAP=15-30`

### Đặt Line và ROI

1. **Chọn vị trí line:**
   - Đặt line ở giữa cửa, vuông góc với hướng di chuyển
   - Tránh đặt quá gần camera (dễ false positive)
   - Test với `demo_video.py` để xem line có đúng không

2. **Tọa độ line:**
   - Format: `LINE__LINE_START=x1,y1` và `LINE__LINE_END=x2,y2`
   - Xác định bằng cách chạy `test_camera.py` và click vào frame để lấy tọa độ
   - Hoặc dùng `demo_video.py` với overlay để debug

3. **ROI (Region of Interest):**
   - Hiện tại chưa có ROI filter, nhưng có thể thêm vào `detector.py`
   - Chỉ detect trong vùng quanh cửa để giảm false positive

### Giảm False Positive

1. **Tăng `MIN_TRACK_LENGTH`:**
   - Mặc định: 5 frames
   - Tăng lên 10-15 để tránh đếm người "đứng lấp ló"

2. **Tăng `COOLDOWN_FRAMES`:**
   - Mặc định: 30 frames
   - Tăng lên 60-90 để tránh double count

3. **Điều chỉnh confidence threshold:**
   - `DETECTION__CONF_THRESHOLD=0.5` (mặc định)
   - Tăng lên 0.6-0.7 để giảm false detection

4. **Xử lý occlusion (nhiều người sát nhau):**
   - ByteTrack tự động xử lý một phần
   - Có thể tăng `TRACK_BUFFER` để track tốt hơn khi bị che khuất

### Failure Modes và Giải pháp

**1. Backlight (ngược sáng):**
- Tăng `CONF_THRESHOLD`
- Sử dụng model lớn hơn (`yolov8s` thay vì `yolov8n`)
- Điều chỉnh camera exposure nếu có thể

**2. Crowded (đông người):**
- Tăng `MIN_TRACK_LENGTH` và `COOLDOWN_FRAMES`
- Giảm `FPS_CAP` để xử lý kỹ hơn
- Cân nhắc dùng model lớn hơn

**3. RTSP connection issues:**
- Tăng `RECONNECT_DELAY` lên 10-15 giây
- Kiểm tra network latency
- Thử giảm resolution của stream nếu có thể

**4. CPU overload:**
- Giảm `FPS_CAP` xuống 5-8
- Dùng `yolov8n.pt`
- Giảm resolution (resize frame trước khi detect)

## Database

SQLite database (`people_counter.db`) chứa:

- **events**: Các sự kiện crossing (timestamp, track_id, direction)
- **aggregations**: Tổng hợp theo window (date, window_type, counts)
- **alerts**: Lịch sử alerts đã gửi

### Query mẫu

```sql
-- Xem events hôm nay
SELECT * FROM events WHERE date(timestamp) = date('now') ORDER BY timestamp DESC;

-- Xem aggregations
SELECT * FROM aggregations ORDER BY date DESC, window_type;

-- Xem alerts
SELECT * FROM alerts ORDER BY sent_at DESC;
```

## Notification

### Telegram

1. Tạo bot với [@BotFather](https://t.me/botfather)
2. Lấy bot token
3. Lấy chat ID (gửi message cho bot, sau đó truy cập `https://api.telegram.org/bot<TOKEN>/getUpdates`)
4. Cấu hình trong `.env`:
```env
NOTIFICATION__ENABLED=true
NOTIFICATION__CHANNEL=telegram
NOTIFICATION__TELEGRAM_BOT_TOKEN=your_token
NOTIFICATION__TELEGRAM_CHAT_ID=your_chat_id
```

### Email

```env
NOTIFICATION__ENABLED=true
NOTIFICATION__CHANNEL=email
NOTIFICATION__EMAIL_SMTP_HOST=smtp.gmail.com
NOTIFICATION__EMAIL_SMTP_PORT=587
NOTIFICATION__EMAIL_FROM=your_email@gmail.com
NOTIFICATION__EMAIL_TO=recipient@gmail.com
NOTIFICATION__EMAIL_PASSWORD=your_app_password
```

### Webhook

```env
NOTIFICATION__ENABLED=true
NOTIFICATION__CHANNEL=webhook
NOTIFICATION__WEBHOOK_URL=https://your-webhook-url.com/alert
```

## Troubleshooting

### Camera không kết nối được

1. **USB camera:**
   - Kiểm tra index: thử `0`, `1`, `2`...
   - Trên Linux: `ls /dev/video*`
   - Trên Windows: thử index `0`, `1`

2. **RTSP stream:**
   - Test với VLC player trước
   - Kiểm tra URL format: `rtsp://user:pass@ip:port/stream`
   - Kiểm tra firewall/network

### Model không load

- YOLO sẽ tự động download model lần đầu
- Kiểm tra internet connection
- Hoặc download thủ công và đặt vào thư mục hiện tại

### FPS thấp

- Giảm `FPS_CAP`
- Dùng model nhỏ hơn (`yolov8n.pt`)
- Giảm resolution (thêm resize trong `camera.py`)
- Kiểm tra CPU/GPU usage

### Đếm sai

- Kiểm tra line position với `demo_video.py`
- Tăng `MIN_TRACK_LENGTH` và `COOLDOWN_FRAMES`
- Điều chỉnh `CONF_THRESHOLD`
- Xem log để debug

## Logs

Logs được ghi vào:
- Console (stdout)
- File: `people_counter.log`

Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`

## Snapshots

Khi có crossing event, snapshot được lưu vào thư mục `snapshots/` (nếu `SAVE_SNAPSHOTS=true`).

Format: `crossing_{track_id}_{direction}_{timestamp}.jpg`

## License

MIT

## Tác giả

Senior Computer Vision Engineer + Backend Engineer

