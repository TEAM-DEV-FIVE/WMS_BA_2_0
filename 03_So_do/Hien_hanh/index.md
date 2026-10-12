# Sơ đồ hiện hành của WMS

Sinh từ mã nguồn và schema PostgreSQL dựng bằng migration 001–026. Các luồng mô tả xử lý trong phần mềm; không đại diện cho khảo sát quy trình doanh nghiệp.

[Ký pháp và nguồn giáo trình](../NOTATION_GUIDE.md). Use case và BPMN dùng bố cục riêng; ERD dùng Crow’s Foot và lực lượng quan hệ suy từ schema. Lớp dùng các ngăn UML.

| Sơ đồ | Nguồn đối chiếu |
|---|---|
| [Kiến trúc ứng dụng hiện tại](svg/ARCHITECTURE.svg) | `apps/desktop/views/shell.py`; `apps/server/api/app.py`; `deploy/lan`; `apps/desktop/local_store/session_vault.py` |
| [Các lớp desktop đang triển khai](svg/CLASS_DESKTOP.svg) | `apps/desktop/views/shell.py`; `apps/desktop/views/orders.py`; `apps/desktop/presenters/orders.py`; `apps/desktop/api/identity.py`; `apps/desktop/local_store/recovery.py`; `apps/desktop/local_store/commands.py` |
| [Các lớp xử lý lệnh trên máy chủ](svg/CLASS_SERVER.svg) | `apps/server/application/orders.py`; `apps/server/application/receipts.py`; `apps/server/application/commands.py`; `apps/server/infrastructure/database.py`; `apps/server/infrastructure/database.py`; `apps/server/application/ports.py` |
| [Các hợp đồng dữ liệu và lỗi đang triển khai](svg/CLASS_CONTRACTS.svg) | `packages/contracts/orders.py`; `packages/contracts/receipts.py`; `packages/contracts/orders.py`; `packages/contracts/receipts.py`; `apps/server/application/commands.py`; `apps/server/domain/errors.py` |
| [Trạng thái chứng từ và điều kiện chuyển](svg/STATE_DOCUMENT.svg) | `apps/server/application/orders.py`; `apps/server/application/receipts.py`; `apps/server/application/issues.py` |
| [Luồng xử lý lệnh và phục hồi ACK](svg/COMMAND_RECOVERY.svg) | `apps/desktop/local_store/recovery.py`; `apps/server/api/recovery.py`; `apps/server/application/commands.py` |
| [Nhận hàng — phê duyệt và ghi sổ](svg/FLOW_RECEIPT.svg) | `apps/server/application/receipts.py`; `apps/server/application/orders.py` |
| [Xuất kho — duyệt, giữ hàng, soạn và ghi sổ](svg/FLOW_ISSUE.svg) | `apps/server/application/issues.py`; `apps/server/application/reservations.py`; `apps/server/application/picking.py` |
| [Kiểm kê — từ phạm vi đếm đến điều chỉnh](svg/FLOW_COUNT.svg) | `apps/server/application/counting.py` |
| [Chuyển kho — xuất transit và nhận tại đích](svg/FLOW_TRANSFER.svg) | `apps/server/application/transfers.py`; `apps/server/application/transfer_stock.py` |
| [Nhập tệp — kiểm tra trước khi commit](svg/FLOW_IMPORT.svg) | `apps/desktop/views/imports.py`; `apps/server/application/imports.py`; `apps/server/application/import_jobs.py` |
| [Tải lại hoặc đóng ứng dụng](svg/FLOW_LIFECYCLE.svg) | `apps/desktop/views/shell.py`; `apps/desktop/lifecycle.py`; `apps/desktop/__main__.py` |
| [Use case — Không gian làm việc](svg/UC_CURRENT_01.svg) | `apps/desktop/views/admin_workspace.py`; `apps/desktop/views/session.py` |
| [Use case — Dữ liệu](svg/UC_CURRENT_02.svg) | `apps/desktop/views/admin_workspace.py`; `apps/desktop/views/master_data.py`; `apps/desktop/views/serial_lookup.py`; `apps/desktop/views/custom_fields.py` |
| [Use case — Nhập hàng](svg/UC_CURRENT_03.svg) | `apps/desktop/views/admin_workspace.py`; `apps/desktop/views/orders.py`; `apps/desktop/views/approvals.py`; `apps/desktop/views/receipts.py`; `apps/desktop/views/openings.py`; `apps/server/application/consignments.py` |
| [Use case — Vận hành kho](svg/UC_CURRENT_04.svg) | `apps/desktop/views/admin_workspace.py`; `apps/desktop/views/issues.py`; `apps/desktop/views/fulfillment.py`; `apps/desktop/views/quality.py`; `apps/desktop/views/moves.py`; `apps/desktop/views/transfers.py`; `apps/desktop/views/returns.py`; `apps/server/application/returns.py` |
| [Use case — Kiểm soát](svg/UC_CURRENT_05.svg) | `apps/desktop/views/admin_workspace.py`; `apps/desktop/views/reports.py`; `apps/desktop/views/counting.py`; `apps/desktop/views/periods.py`; `apps/desktop/views/reversals.py` |
| [Use case — Công cụ & hệ thống](svg/UC_CURRENT_06.svg) | `apps/desktop/views/admin_workspace.py`; `apps/desktop/views/imports.py`; `apps/desktop/printing/view.py`; `apps/desktop/views/admin.py`; `apps/desktop/views/recovery.py`; `apps/desktop/views/receipt_recovery.py`; `apps/desktop/views/shell.py` |
| [Vai trò và quyền seed · Kiểm toán](svg/ROLE_AUDITOR.svg) | `04_Phan_quyen/current_permissions.json`; `migrations/*.sql` |
| [Vai trò và quyền seed · Mua hàng](svg/ROLE_BUYER.svg) | `04_Phan_quyen/current_permissions.json`; `migrations/*.sql` |
| [Vai trò và quyền seed · Kiểm soát/kế toán](svg/ROLE_CONTROLLER.svg) | `04_Phan_quyen/current_permissions.json`; `migrations/*.sql` |
| [Vai trò và quyền seed · Ban điều hành](svg/ROLE_DIRECTOR.svg) | `04_Phan_quyen/current_permissions.json`; `migrations/*.sql` |
| [Vai trò và quyền seed · Quản lý danh mục](svg/ROLE_MASTER_DATA.svg) | `04_Phan_quyen/current_permissions.json`; `migrations/*.sql` |
| [Vai trò và quyền seed · Nhân viên soạn/xuất](svg/ROLE_PICKER.svg) | `04_Phan_quyen/current_permissions.json`; `migrations/*.sql` |
| [Vai trò và quyền seed · Nhân viên nhận](svg/ROLE_RECEIVER.svg) | `04_Phan_quyen/current_permissions.json`; `migrations/*.sql` |
| [Vai trò và quyền seed · Bán hàng](svg/ROLE_SELLER.svg) | `04_Phan_quyen/current_permissions.json`; `migrations/*.sql` |
| [Vai trò và quyền seed · Quản trị kỹ thuật](svg/ROLE_SYSADMIN.svg) | `04_Phan_quyen/current_permissions.json`; `migrations/*.sql` |
| [Vai trò và quyền seed · Quản lý kho](svg/ROLE_WAREHOUSE_MANAGER.svg) | `04_Phan_quyen/current_permissions.json`; `migrations/*.sql` |
| [ERD · app_user](svg/ERD_app_user.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · approval_policy](svg/ERD_approval_policy.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · approval_policy_step](svg/ERD_approval_policy_step.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · approval_request](svg/ERD_approval_request.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · approval_step](svg/ERD_approval_step.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · audit_event](svg/ERD_audit_event.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · auth_challenge](svg/ERD_auth_challenge.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · auth_contact](svg/ERD_auth_contact.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · auth_contact_challenge](svg/ERD_auth_contact_challenge.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · auth_delivery](svg/ERD_auth_delivery.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · auth_google_flow](svg/ERD_auth_google_flow.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · auth_google_identity](svg/ERD_auth_google_identity.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · auth_password_reset](svg/ERD_auth_password_reset.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · auth_recovery_code](svg/ERD_auth_recovery_code.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · auth_self_reset](svg/ERD_auth_self_reset.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · auth_session](svg/ERD_auth_session.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · auth_throttle](svg/ERD_auth_throttle.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · auth_token](svg/ERD_auth_token.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · barcode](svg/ERD_barcode.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · client_release](svg/ERD_client_release.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · consignment_agreement](svg/ERD_consignment_agreement.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · consignment_receipt](svg/ERD_consignment_receipt.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · consignment_receipt_line](svg/ERD_consignment_receipt_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · consumer_receipt](svg/ERD_consumer_receipt.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · count_assignment](svg/ERD_count_assignment.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · count_decision](svg/ERD_count_decision.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · count_empty_confirmation](svg/ERD_count_empty_confirmation.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · count_execution](svg/ERD_count_execution.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · count_line](svg/ERD_count_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · count_location_lock](svg/ERD_count_location_lock.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · count_observation](svg/ERD_count_observation.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · count_scope](svg/ERD_count_scope.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · count_session](svg/ERD_count_session.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · count_submission](svg/ERD_count_submission.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · custom_field_binding](svg/ERD_custom_field_binding.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · custom_field_change](svg/ERD_custom_field_change.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · custom_field_definition](svg/ERD_custom_field_definition.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · custom_field_revision](svg/ERD_custom_field_revision.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · custom_field_schema](svg/ERD_custom_field_schema.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · document](svg/ERD_document.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · document_assignment](svg/ERD_document_assignment.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · document_attachment](svg/ERD_document_attachment.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · document_line](svg/ERD_document_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · document_link](svg/ERD_document_link.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · export_job](svg/ERD_export_job.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · export_task](svg/ERD_export_task.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · fulfillment_consumption](svg/ERD_fulfillment_consumption.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · grant_request](svg/ERD_grant_request.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · idempotency_record](svg/ERD_idempotency_record.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · import_document_source](svg/ERD_import_document_source.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · import_file](svg/ERD_import_file.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · import_job](svg/ERD_import_job.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · import_row](svg/ERD_import_row.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · import_task](svg/ERD_import_task.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · inventory_transaction](svg/ERD_inventory_transaction.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · issue_document](svg/ERD_issue_document.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · location](svg/ERD_location.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · lot](svg/ERD_lot.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · mfa_factor](svg/ERD_mfa_factor.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · move_line](svg/ERD_move_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · opening_document](svg/ERD_opening_document.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · opening_line](svg/ERD_opening_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · organization](svg/ERD_organization.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · outbox_event](svg/ERD_outbox_event.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · package](svg/ERD_package.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · package_line](svg/ERD_package_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · partner](svg/ERD_partner.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · period_reopen_confirmation](svg/ERD_period_reopen_confirmation.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · permission](svg/ERD_permission.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · pick_task](svg/ERD_pick_task.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · print_attempt](svg/ERD_print_attempt.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · print_job](svg/ERD_print_job.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · print_task](svg/ERD_print_task.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · product](svg/ERD_product.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · product_category](svg/ERD_product_category.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · product_image](svg/ERD_product_image.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · product_uom](svg/ERD_product_uom.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · quality_decision](svg/ERD_quality_decision.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · reference_price](svg/ERD_reference_price.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · report_request_guard](svg/ERD_report_request_guard.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · report_snapshot](svg/ERD_report_snapshot.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · report_snapshot_row](svg/ERD_report_snapshot_row.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · reservation](svg/ERD_reservation.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · reservation_consumption](svg/ERD_reservation_consumption.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · return_document](svg/ERD_return_document.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · return_line](svg/ERD_return_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · reversal_document](svg/ERD_reversal_document.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · reversal_line](svg/ERD_reversal_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · role](svg/ERD_role.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · role_permission](svg/ERD_role_permission.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · serial](svg/ERD_serial.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · serial_position](svg/ERD_serial_position.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · serial_warranty_record](svg/ERD_serial_warranty_record.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · stock_balance](svg/ERD_stock_balance.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · stock_item](svg/ERD_stock_item.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · stock_move](svg/ERD_stock_move.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · stock_owner](svg/ERD_stock_owner.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · stock_period](svg/ERD_stock_period.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · stored_file](svg/ERD_stored_file.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · transfer_adjustment](svg/ERD_transfer_adjustment.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · transfer_discrepancy](svg/ERD_transfer_discrepancy.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · transfer_line](svg/ERD_transfer_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · transfer_move](svg/ERD_transfer_move.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · uom](svg/ERD_uom.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · user_avatar](svg/ERD_user_avatar.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · user_role_grant](svg/ERD_user_role_grant.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · warehouse](svg/ERD_warehouse.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD · worker_status](svg/ERD_worker_status.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
