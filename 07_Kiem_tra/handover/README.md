# Ma trận bàn giao

`requirements.csv` ánh xạ đủ49 yêu cầu từ `01_Tai_lieu/BA/requirements.json` vào mã hiện hành,
test thành phần, tài liệu và báo cáo bàn giao có evidence. Tên owner trong baseline là vai trò
nghiệm thu; đầu mối kỹ thuật hiện tại Trần Trung Kiên. Không tự phân công các thành viên lịch sử
đã rời dự án và không tự điền người ký thay họ.

`verification=COMPONENT_EVIDENCE_LINKED` nghĩa là đã dẫn tới báo cáo thành phần, **không phải**
đã chạy chính xác scenario UAT. `remaining` nêu phần chưa đo/duyệt; `acceptance_status=PLANNED`.
T01–T28 đều được ánh xạ nhưng cần evidence từng bước và reviewer thật trong B26.

Kiểm tra đường dẫn và coverage bằng:

```bash
rtk proxy python3 07_Kiem_tra/handover/check.py
```

B25 không thay số liệu/approval trong baseline, không sửa các acceptance test gốc hoặc đóng issue.
Tài liệu bắt đầu tại [HANDOVER](../../01_Tai_lieu/HANDOVER.md).
