# Architecture Overview

## Tổng quan

People Counter MVP được thiết kế theo kiến trúc modular, dễ mở rộng và bảo trì.

## Kiến trúc

```
┌─────────────────────────────────────────────────────────┐
│                    Main Application                      │
│                      (main.py)                          │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
┌───────▼────────┐      ┌─────────▼──────────┐
│  Camera Stream │      │   Scheduler        │
│   (camera.py)  │      │  (scheduler.py)    │
└───────┬────────┘      └─────────┬──────────┘
        │                         │
        │                         │
┌───────▼────────┐      ┌─────────▼──────────┐
│   Detector     │      │     Storage        │
│ (detector.py)  │      │   (storage.py)     │
└───────┬────────┘      └─────────┬──────────┘
        │                         │
        │                         │
┌───────▼────────┐      ┌─────────▼──────────┐
│    Tracker     │      │    Notifier        │
│  (tracker.py)  │      │  (notifier.py)     │
└───────┬────────┘      └────────────────────┘
        │
        │
┌───────▼────────┐
│ Line Counter  │
│(line_counter.py)│
└────────────────┘
```

## Components

### 1. Configuration (`config.py`)

- Sử dụng Pydantic Settings để quản lý cấu hình
- Hỗ trợ environment variables với nested delimiter `__`
- Type validation và default values
- Các config classes:
  - `CameraConfig`: Camera settings
  - `DetectionConfig`: YOLO model settings
  - `TrackingConfig`: Tracker settings
  - `LineConfig`: Line crossing settings
  - `WindowConfig`: Time window settings
  - `NotificationConfig`: Notification settings
  - `LoggingConfig`: Logging settings

### 2. Camera (`camera.py`)

- **CameraStream**: Quản lý camera stream
  - Hỗ trợ USB camera và RTSP stream
  - Tự động reconnect khi mất kết nối
  - FPS capping để kiểm soát performance
  - FPS calculation và monitoring

### 3. Detection (`detector.py`)

- **PersonDetector**: Person detection với YOLO
  - Sử dụng Ultralytics YOLO
  - Chỉ detect class "person" (class_id=0)
  - Configurable confidence và IOU thresholds
  - Trả về bounding boxes: (x1, y1, x2, y2, conf)

### 4. Tracking (`tracker.py`)

- **Tracker**: Object tracking wrapper
  - Hỗ trợ ByteTrack (built-in ultralytics)
  - Hỗ trợ DeepSORT (optional)
  - Track ID assignment và persistence
  - Trả về tracks: (track_id, x1, y1, x2, y2, conf)

### 5. Line Counter (`line_counter.py`)

- **LineCounter**: Line crossing detection
  - Virtual line được định nghĩa bởi 2 điểm
  - Tính toán signed distance từ centroid đến line
  - Phát hiện crossing khi sign thay đổi
  - Chống double count với cooldown mechanism
  - Track history để đảm bảo min_track_length
  - Trả về direction: "in" hoặc "out"

### 6. Storage (`storage.py`)

- **Storage**: SQLite database management
  - **events table**: Lưu từng crossing event
  - **aggregations table**: Tổng hợp theo window
  - **alerts table**: Lịch sử alerts
  - Timezone-aware timestamps
  - Indexes cho performance

### 7. Scheduler (`scheduler.py`)

- **WindowScheduler**: Time window và alert management
  - Sử dụng APScheduler với cron triggers
  - Tự động aggregate window A và B
  - Kiểm tra điều kiện OUT_A > IN_B
  - Trigger notification khi cần
  - Timezone-aware scheduling

### 8. Notifier (`notifier.py`)

- **Notifier**: Multi-channel notification
  - **Telegram**: Bot API
  - **Email**: SMTP
  - **Webhook**: HTTP POST
  - Plugin-based design, dễ thêm channel mới

### 9. Main Application (`main.py`)

- **PeopleCounterApp**: Main orchestration
  - Khởi tạo tất cả components
  - Main loop: read → detect → track → count → save
  - Signal handling (SIGINT, SIGTERM)
  - Metrics logging
  - Snapshot saving (optional)

## Data Flow

```
Camera Frame
    ↓
Detection (YOLO)
    ↓
Tracking (ByteTrack)
    ↓
Line Crossing Detection
    ↓
Event Storage (SQLite)
    ↓
Aggregation (Scheduler)
    ↓
Alert Check (Scheduler)
    ↓
Notification (if needed)
```

## Database Schema

### events
- `id`: Primary key
- `timestamp`: ISO format timestamp
- `track_id`: Track ID
- `direction`: "in" or "out"
- `camera_id`: Camera identifier
- `created_at`: Creation timestamp

### aggregations
- `id`: Primary key
- `date`: Date (YYYY-MM-DD)
- `window_type`: "A" or "B"
- `window_start`: Window start time
- `window_end`: Window end time
- `count_in`: Total IN count
- `count_out`: Total OUT count
- `camera_id`: Camera identifier
- `calculated_at`: Calculation timestamp

### alerts
- `id`: Primary key
- `date`: Date (YYYY-MM-DD)
- `window_a_out`: OUT count for window A
- `window_b_in`: IN count for window B
- `difference`: OUT_A - IN_B
- `camera_id`: Camera identifier
- `sent_at`: Alert timestamp
- `notification_channel`: Channel used
- `notification_status`: "sent" or "failed"

## Design Patterns

1. **Dependency Injection**: Components được inject vào main app
2. **Configuration Pattern**: Centralized config với Pydantic
3. **Plugin Pattern**: Notifier hỗ trợ multiple channels
4. **Observer Pattern**: Scheduler observes time windows
5. **Factory Pattern**: Tracker factory cho different types

## Performance Considerations

1. **FPS Capping**: Giới hạn số frame xử lý mỗi giây
2. **Model Selection**: Chọn model phù hợp với hardware
3. **Database Indexing**: Indexes trên timestamp và date
4. **Track History Limiting**: Giới hạn history để tránh memory leak
5. **Async Operations**: Scheduler chạy background, không block main loop

## Extensibility

### Thêm Tracker mới

1. Implement tracker interface trong `tracker.py`
2. Add vào `Tracker.__init__`
3. Update `update()` method

### Thêm Notification Channel

1. Add config trong `NotificationConfig`
2. Implement method trong `Notifier`
3. Update `send()` method

### Thêm Detection Model

1. Implement detector interface trong `detector.py`
2. Update `PersonDetector` hoặc tạo class mới
3. Update `main.py` để sử dụng detector mới

## Testing Strategy

1. **Unit Tests**: Test từng component riêng lẻ
2. **Integration Tests**: Test flow end-to-end
3. **Demo Scripts**: `demo_video.py` để test với video file
4. **Camera Test**: `test_camera.py` để verify camera connection

## Deployment Considerations

1. **Headless Mode**: Không cần display (comment out cv2.imshow)
2. **Log Rotation**: Cần implement log rotation cho production
3. **Database Backup**: Cần backup SQLite database định kỳ
4. **Resource Monitoring**: Monitor CPU, memory, disk usage
5. **Error Recovery**: Automatic restart với systemd/supervisor

