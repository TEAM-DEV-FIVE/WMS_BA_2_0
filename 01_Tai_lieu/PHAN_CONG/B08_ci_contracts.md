# B08 — CI, hợp đồng API và nền kiểm thử

- Nhánh: `agent/b08-ci-contracts`
- Worktree: `/home/kien/Đồ án KHMT2_2/worktrees/wms-b08-ci-contracts`
- Trạng thái ban đầu: **READY**, ưu tiên **P1**.
- Phụ thuộc: Không có phụ thuộc mới; nền 06041b7 đã có.
- Issues liên quan: [#2](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/2), [#3](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/3), [#11](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/11), [#20](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/20), [#21](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/21), [#4](https://github.com/TEAM-DEV-FIVE/WMS_BA_2_0/issues/4) (đối chiếu snapshot local).
- Yêu cầu: TR02, TR03, TR04, NFR08.
- Bằng chứng liên quan: T02, T07, T11, T14, T24; đây là phân công kiểm thử, chưa phải PASS.
- Báo cáo tạo mới khi bàn giao: `01_Tai_lieu/PHAN_CONG/BAN_GIAO/B08.md`.

Đọc [quy trình chung](QUY_TRINH_AGENT.md), [bảng toàn bộ công việc](KE_HOACH_CON_LAI.md) và AGENTS.md trước khi sửa.

## Phạm vi cần hoàn thành

1. Review runtime OpenAPI so với thiết kế nhập sẵn; ghi rõ implemented/planned, kiểm tra permission/version/idempotency và response lỗi cho contract đang có. Giữ planned APIs, không giả runtime hỗ trợ hết.
2. CI lint/unit/PG15-16/GUI Linux/build+cài wheel; job Windows phù hợp và artifact log có commit/environment. Sửa runner để test module mới được thu thập tự động.
3. Kiểm tra architecture desktop chỉ gọi API, package imports ngoài source và migration readiness; giữ workflow có thể chạy local.
4. Review flow UI gốc và lập checklist acceptance/traceability xuyên domain; B24/B26 hoàn thiện bằng chứng tích hợp sau các nhánh.
5. Được đề xuất/cập nhật dependencies phục vụ CI, ghi lock diff và phối hợp điều phối; không tự push để tạo bằng chứng CI giả.

## Phạm vi sửa chính

- `.github/workflows/`
- `scripts/check_application.py, check_postgres.py, export_runtime_contract.py`
- `tests/foundation/test_api_contracts.py, test_runtime_contract.py`
- `05_API/ và tài liệu kiểm thử/contract liên quan`

Không cấp PostgreSQL revision mới mặc định cho nhánh này; báo điều phối nếu có nhu cầu DDL.

Test/fixture, tài liệu module và báo cáo riêng thuộc cùng nhánh. Các đường dẫn module mới là đề xuất; giữ ranh giới trách nhiệm. File dùng chung chỉ sửa hook cần thiết và liệt kê trong báo cáo.

## Kiểm thử và điều kiện bàn giao

- Chạy các job tương đương local khả dụng, export contract tái lập và wheel import ngoài repo.
- Negative contract tests có thiếu quyền/stale/unknown operation; kiểm tra CI không bỏ integration vì marker sai.
- Ghi NOT_RUN cho hosted CI/Windows chưa thực chạy; không biến file YAML thành bằng chứng pass.
- Chạy các kiểm tra phù hợp trong quy trình chung; báo cáo lệnh/kết quả/môi trường. Code cần API/DB phải kiểm thử qua API/PG thật, GUI có kiểm chứng đúng phiên và thread.
- Contract/schema/policy thay đổi phải kèm artifacts tương ứng, rollback/race/idempotency theo phạm vi. Không sửa/xóa/skip test để có kết quả xanh.

## Đầu vào để nghiệm thu đầy đủ

- Hosted CI chỉ có kết quả sau khi người dùng đưa commit lên GitHub; Windows cần runner Windows thật.

Tiếp tục phần local làm được; ghi rõ NEEDS_ENVIRONMENT/NOT_RUN cho phần chưa có bằng chứng.

## Prompt giao agent

```text
Làm việc tại /home/kien/Đồ án KHMT2_2/worktrees/wms-b08-ci-contracts, nhánh agent/b08-ci-contracts. Đọc AGENTS.md, 01_Tai_lieu/PHAN_CONG/B08_ci_contracts.md và 01_Tai_lieu/PHAN_CONG/QUY_TRINH_AGENT.md. Kiểm tra trạng thái phụ thuộc trên nhánh điều phối trước khi bắt đầu. Triển khai đủ phạm vi được giao, kiểm thử theo brief, ghi báo cáo 01_Tai_lieu/PHAN_CONG/BAN_GIAO/B08.md, commit local rồi bàn giao hash. Không tự push/merge hoặc đổi trạng thái nghiệm thu tổng. Nếu thiếu dependency/môi trường, nêu cụ thể và tiếp tục phần độc lập; không dùng mock làm bằng chứng hoàn tất.
```
