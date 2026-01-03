# Gate Counter - Hướng dẫn sử dụng

## Tổng quan

Gate Counter sử dụng **band-based crossing detection** thay vì line mỏng, giúp giảm jitter và đếm chính xác hơn.

## Cấu hình Gate

### HORIZONTAL_BAND (Khuyến nghị cho cửa ngang)

Cấu hình trong `.env`:

```env
GATE__GATE_MODE=HORIZONTAL_BAND
GATE__GATE_Y=240.0          # Y trung tâm của band (giữa frame)
GATE__GATE_HEIGHT=40.0      # Độ dày band (pixels)
GATE__GATE_X_MIN=           # Tùy chọn: X tối thiểu (để trống = 0)
GATE__GATE_X_MAX=           # Tùy chọn: X tối đa (để trống = width)
```

**Ví dụ:**
- Frame 640x480: `GATE_Y=240` (giữa theo chiều dọc)
- Band dày 40px: `GATE_HEIGHT=40`
- Band ngang toàn bộ: `GATE_X_MIN=` và `GATE_X_MAX=` (để trống)

### LINE_BAND (Cho cửa chéo)

```env
GATE__GATE_MODE=LINE_BAND
GATE__GATE_P1=[0,240]       # Điểm đầu (x, y)
GATE__GATE_P2=[640,240]     # Điểm cuối (x, y)
GATE__GATE_THICKNESS=40.0   # Độ dày band quanh line
```

## Direction Mapping

### HORIZONTAL_BAND

```env
# TOP -> BOTTOM = OUT (đi xuống = ra)
GATE__DIRECTION_MAPPING_TOP_BOTTOM=OUT

# BOTTOM -> TOP = IN (đi lên = vào)
GATE__DIRECTION_MAPPING_BOTTOM_TOP=IN
```

**Lưu ý:** Có thể đảo ngược tùy theo hướng camera:
- Camera nhìn từ trên xuống: TOP->BOTTOM = OUT
- Camera nhìn từ dưới lên: TOP->BOTTOM = IN

### LINE_BAND

Mặc định:
- LEFT -> RIGHT = IN
- RIGHT -> LEFT = OUT

## Anti-Jitter Parameters

```env
# Cooldown: thời gian chờ trước khi count lại cùng track_id (giây)
GATE__COOLDOWN_SEC=1.0

# Min frames in gate: số frame tối thiểu trong gate trước khi count
GATE__MIN_FRAMES_IN_GATE=2

# Min travel: khoảng cách di chuyển tối thiểu trong gate (pixels)
GATE__MIN_TRAVEL_PX=15.0
```

**Tuning guide:**
- **Đếm sai nhiều (false positive):**
  - Tăng `COOLDOWN_SEC` lên 2.0-3.0
  - Tăng `MIN_FRAMES_IN_GATE` lên 5-10
  - Tăng `MIN_TRAVEL_PX` lên 30-50

- **Bỏ sót (false negative):**
  - Giảm `MIN_FRAMES_IN_GATE` xuống 1
  - Giảm `MIN_TRAVEL_PX` xuống 10
  - Giảm `COOLDOWN_SEC` xuống 0.5

## Cách xác định GATE_Y và GATE_HEIGHT

1. **Chạy test camera:**
   ```bash
   python scripts/test_camera.py
   ```

2. **Quan sát frame:**
   - Xác định vị trí cửa trong frame
   - Ghi lại tọa độ Y của giữa cửa

3. **Tính GATE_Y:**
   - Nếu frame height = 480, giữa = 240
   - Điều chỉnh theo vị trí cửa thực tế

4. **Tính GATE_HEIGHT:**
   - Band nên dày ít nhất 30-50px để giảm jitter
   - Không quá dày (tránh đếm khi chưa qua cửa)

## Logic State Machine

Gate Counter sử dụng state machine để xác định crossing:

1. **Outside gate** → Track ở ngoài band
2. **Entering gate** → Track đi vào band (ghi nhận entry_side)
3. **Inside gate** → Track ở trong band (đếm frames_in_gate)
4. **Exiting gate** → Track rời band (xác định exit_side)
5. **Count condition:**
   - `frames_in_gate >= min_frames_in_gate`
   - `entry_side != exit_side` (phải qua sang phía đối diện)
   - `travel_distance >= min_travel_px` (phải di chuyển đủ xa)
   - Không trong cooldown

## Overlay Visualization

- **Magenta rectangle:** Gate band (semi-transparent)
- **Red bounding boxes:** Detected persons
- **Red circles:** Bottom-center points (tracking points)
- **Green arrow (↑):** IN direction với count
- **Red arrow (↓):** OUT direction với count
- **Text overlay:** IN/OUT counts, FPS, active tracks

## Troubleshooting

### Đếm sai (IN=8, OUT=2 khi chỉ có 1 người)

**Nguyên nhân:**
- Track bị mất và tạo lại nhiều lần
- Cooldown không đủ
- Gate quá rộng hoặc vị trí sai

**Giải pháp:**
1. Tăng `COOLDOWN_SEC` lên 2.0-3.0
2. Tăng `MIN_FRAMES_IN_GATE` lên 5-10
3. Kiểm tra gate position (có thể đặt sai vị trí)
4. Giảm `GATE_HEIGHT` nếu quá rộng

### Không đếm được

**Nguyên nhân:**
- Gate position sai
- Threshold quá cao
- Track không ổn định

**Giải pháp:**
1. Kiểm tra gate position với overlay
2. Giảm `MIN_FRAMES_IN_GATE` xuống 1
3. Giảm `MIN_TRAVEL_PX` xuống 10
4. Kiểm tra tracking (track_id có ổn định không)

### Jitter (rung qua lại)

**Giải pháp:**
1. Tăng `GATE_HEIGHT` (band dày hơn)
2. Tăng `MIN_FRAMES_IN_GATE`
3. Tăng `COOLDOWN_SEC`

## Test với Video

```bash
python scripts/demo_video.py path/to/video.mp4 --fps 10
```

Script sẽ hiển thị overlay với gate band và arrows để bạn có thể tune parameters.

## Best Practices

1. **Gate position:**
   - Đặt ở giữa cửa, vuông góc với hướng di chuyển
   - Không quá gần camera (dễ false positive)

2. **Band thickness:**
   - Tối thiểu 30px, khuyến nghị 40-60px
   - Đủ dày để giảm jitter nhưng không quá rộng

3. **Anti-jitter:**
   - Bắt đầu với defaults
   - Tăng dần nếu có false positive
   - Giảm nếu bỏ sót

4. **Direction mapping:**
   - Test với 1 người đi qua và quan sát
   - Điều chỉnh mapping nếu IN/OUT bị đảo ngược

