# Mốc tích hợp phụ thuộc B09

Ngày 2026-10-03. Người dùng giao thêm review/tích hợp để mở B09; thực hiện trên
`feat/application-foundation`, từ `45e51a55004b6e808b5b051a757a77a265df1d05`.

| Nhánh | Head đã review | Merge local |
|---|---|---|
| B01 | b70d43ac8e16b2744b023091e42fa56f9068a6a5 | 97ee359 |
| B02 | 9d3fbd1177d27350c73163885ab65260b9d72ec2 | 5a89542 |
| B03 | dd659b620a9160854f24aa09cc40718414703574 | 9a48666 |
| B05 | 784e6697c72c741e78a635995174503231d3c287 | 08286fa |
| B06 | cb1c99d632cbe58facd97039ccb2ee28b1d37523 | 12c6a8a |

Giữ đầy đủ router/lifecycle/snapshot và desktop của cả 5 nhánh. Chốt các revision
chưa phát hành 011 B01, 012 B02, 013 B03. Sửa xung đột seed policy/step B03 sang
ID đuôi 106/116 để không đè ISSUE 105/115. Không sửa migration 001–010 hoặc
worktree tính năng nguồn. Schema tổng: 70 bảng, 481 cột, 144 FK; OpenAPI 92 paths.

Kiểm chứng PostgreSQL tạm và Tk/Xvfb trên Linux, PYTHONPATH đúng checkout:

- `rtk proxy env PYTHONPATH="$PWD" PYTEST_ADDOPTS='-k "b09_dependency or upgrade or schema_matches" -x' .venv/bin/python scripts/check_application.py`: **15 passed**, 454 deselected. XML local `.reports/b09-dependency-upgrade.xml`.
- `rtk proxy env PYTHONPATH="$PWD" xvfb-run -a .venv/bin/python scripts/check_application.py --gui`: **469 passed + 10 subtests**, 0 failed/skip, 433.49s. XML local `.reports/b09-dependencies-full.xml`.
- Ruff toàn bộ apps/packages/tests/foundation và runner: đạt.
- Test mới `tests/foundation/test_b09_dependencies.py` kiểm upgrade prefix 010/011/012,
  bảo toàn policy và luồng thực nhận 80 → QC 75/5 → cất hàng → giữ 70 → xuất 30 →
  đóng thiếu giải phóng 40 → move 6. Move đã duyệt không lấy được tồn đang giữ chỗ.

Sổ tích hợp trỏ tới commit kiểm chứng chứa cả 5 nhánh và test này, sau đó B09 được
đồng bộ bằng merge có giữ commit nghiên cứu riêng. Không push/deploy. Windows,
hardware, tải và DR: NOT_RUN; T01–T28 vẫn PLANNED. Chính sách thương mại ký gửi
chưa được cung cấp; việc tích hợp này chỉ mở dependency, không xác nhận UAT B09.
