# Alert System Fix Summary

## Issues Found

1. **PhaseManager không tự động tạo missing period khi app restart**
   - `active_missing_periods` dict bị reset về rỗng khi app restart
   - PhaseManager chỉ kiểm tra dict, không kiểm tra database
   - Missing period phải được tạo thủ công bằng script

2. **Missing period start_time không đúng**
   - Missing period được tạo với start_time = current time
   - Nên là start_time từ khi session bắt đầu (13:00 cho afternoon, 08:30 cho morning)

3. **Unicode encoding errors trong logs**
   - Các comment tiếng Việt gây lỗi khi in ra console Windows

## Fixes Applied

1. **PhaseManager._check_phase_and_missing() updated**:
   - Kiểm tra database (`get_active_missing_period`) trước khi tạo missing period mới
   - Sync `active_missing_periods` dict với database khi app restart
   - Tự động tạo missing period với start_time đúng (13:00 cho afternoon, 08:30 cho morning)

2. **Unicode errors fixed**:
   - Thay các comment tiếng Việt bằng tiếng Anh trong `app/alert_manager.py`
   - Sửa các print statement có ký tự Unicode

3. **Alert logic confirmed**:
   - Alert đã được gửi lúc 14:49:50 với missing=11, status=sent
   - Cooldown logic hoạt động đúng (skip alert nếu < 30 phút và missing count không đổi)
   - Email sending hoạt động (test email đã gửi thành công)

## Email Status

- **Alert sent**: 2026-01-09 14:49:50
- **Missing count**: 11
- **Status**: sent
- **Recipient**: viethoanggm2003@gmail.com
- **From**: meragroup.tech@gmail.com

## Next Steps

1. Kiểm tra hộp thư (inbox và spam/junk folder)
2. Nếu không thấy email, kiểm tra:
   - Gmail App Password có đúng không
   - Firewall/antivirus có chặn SMTP không
   - Email có bị delay không

3. PhaseManager sẽ tự động tạo missing period khi app chạy (không cần script thủ công nữa)

## Testing

Để test alert system:
```bash
python force_alert_check_now.py
```

Để test email sending:
```bash
python test_email_send_direct.py
```

## Alert Schedule

- **Alert check interval**: 30 phút
- **Alert delay**: 30 giây (trước khi bắt đầu đếm)
- **Alert duration**: 30 phút (sau delay)
- **Total**: 30.5 phút từ khi phát hiện missing
- **Cooldown**: 30 phút giữa các alert nếu missing count không đổi
