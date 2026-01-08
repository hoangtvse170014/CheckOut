# Camera Setup Guide

## Vấn đề: Camera không hiển thị trên web dashboard

### Nguyên nhân:
FastAPI web server (port 8000) cần frame từ app chính (people counter app). Nếu app chính không chạy, camera sẽ không có frame để hiển thị.

## Giải pháp:

### Cách 1: Chạy cả hai cùng lúc (Khuyên dùng)

```bash
python start_all.py
```

Script này sẽ tự động chạy cả FastAPI server và main app.

### Cách 2: Chạy từng cái riêng

**Terminal 1 - FastAPI Server:**
```bash
python start_web_server.py
```

**Terminal 2 - Main App:**
```bash
python scripts/run.py
```

### Cách 3: Kiểm tra app chính có đang chạy

Nếu app chính đã chạy nhưng camera vẫn không hiển thị:

1. **Kiểm tra import:**
   - Đảm bảo `web_api_server.py` có thể import được
   - App chính sẽ tự động cập nhật frame vào FastAPI server

2. **Restart cả hai:**
   - Dừng cả hai services
   - Chạy lại theo thứ tự: FastAPI server trước, sau đó main app

3. **Kiểm tra camera:**
   ```bash
   python -c "import cv2; cap = cv2.VideoCapture(0); print('Camera OK:', cap.isOpened()); cap.release()"
   ```

## Lưu ý:

- **Main app phải chạy** để có camera feed
- FastAPI server chỉ hiển thị frame từ main app
- Nếu chỉ chạy FastAPI server, sẽ hiển thị "Camera not available"
- Camera index 0 thường là USB camera đầu tiên

## Debug:

Nếu vẫn không hiển thị, kiểm tra:
1. Console log của FastAPI server - xem có lỗi gì không
2. Console log của main app - xem camera có kết nối được không
3. Task Manager - xem cả hai process có đang chạy không

