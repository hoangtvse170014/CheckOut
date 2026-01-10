# Hướng Dẫn Enable Email Alert

## Vấn Đề Hiện Tại

- ❌ Email không được enable trong `.env` file
- ❌ Missing period mới được tạo, chưa đủ 30.5 phút

## Cách Enable Email

### 1. Mở file `.env` và thêm/sửa các dòng sau:

```env
# Enable notifications
NOTIFICATION__ENABLED=true

# Set channel to email
NOTIFICATION__CHANNEL=email

# Email SMTP configuration
NOTIFICATION__EMAIL_SMTP_HOST=smtp.gmail.com
NOTIFICATION__EMAIL_SMTP_PORT=587

# Email credentials
NOTIFICATION__EMAIL_FROM=your-email@gmail.com
NOTIFICATION__EMAIL_TO=recipient1@gmail.com,recipient2@gmail.com
NOTIFICATION__EMAIL_PASSWORD=your-app-password
```

### 2. Gmail App Password

Nếu dùng Gmail, bạn cần tạo **App Password** (không dùng mật khẩu thông thường):

1. Vào Google Account: https://myaccount.google.com/
2. Security → 2-Step Verification (phải bật trước)
3. App passwords → Generate app password
4. Copy password và paste vào `NOTIFICATION__EMAIL_PASSWORD`

### 3. Restart App

Sau khi sửa `.env`, restart app để áp dụng cấu hình mới.

## Test Email

Sau khi enable, chạy script test:
```bash
python test_email.py
```

## Kiểm Tra Alert Status

Chạy script để kiểm tra:
```bash
python check_alert_status.py
```
