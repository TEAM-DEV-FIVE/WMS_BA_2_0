# Sơ đồ hiện hành của WMS

Sinh từ mã nguồn và schema PostgreSQL dựng bằng migration 001–026. Các luồng mô tả xử lý trong phần mềm; không đại diện cho khảo sát quy trình doanh nghiệp.

ERD: dấu ? là nullable; mũi tên biểu diễn FK từ cột nguồn sang cột đích. PK ghép, CHECK, UNIQUE và index đầy đủ trong `02_CSDL/current/schema.json`.

| Sơ đồ | Nguồn đối chiếu |
|---|---|
| [Kiến trúc ứng dụng hiện tại](svg/ARCHITECTURE.svg) | `apps/desktop/views/shell.py`; `apps/server/api/app.py`; `deploy/lan`; `apps/desktop/local_store/session_vault.py` |
| [Các lớp desktop đang triển khai](svg/CLASS_DESKTOP.svg) | `apps/desktop/views/shell.py`; `apps/desktop/views/orders.py`; `apps/desktop/presenters/orders.py`; `apps/desktop/api/identity.py`; `apps/desktop/local_store/recovery.py`; `apps/desktop/local_store/commands.py` |
| [Các lớp xử lý lệnh trên máy chủ](svg/CLASS_SERVER.svg) | `apps/server/application/orders.py`; `apps/server/application/receipts.py`; `apps/server/application/commands.py`; `apps/server/infrastructure/database.py`; `apps/server/infrastructure/database.py`; `apps/server/application/ports.py` |
| [Các hợp đồng dữ liệu và lỗi đang triển khai](svg/CLASS_CONTRACTS.svg) | `packages/contracts/orders.py`; `packages/contracts/receipts.py`; `packages/contracts/orders.py`; `packages/contracts/receipts.py`; `apps/server/application/commands.py`; `apps/server/domain/errors.py` |
| [Trạng thái chứng từ và điều kiện chuyển](svg/STATE_DOCUMENT.svg) | `apps/server/application/orders.py`; `apps/server/application/receipts.py`; `apps/server/application/issues.py` |
| [Luồng xử lý lệnh và phục hồi ACK](svg/COMMAND_RECOVERY.svg) | `apps/desktop/local_store/recovery.py`; `apps/server/api/recovery.py`; `apps/server/application/commands.py` |
| [Luồng nhận hàng trong phần mềm](svg/FLOW_RECEIPT.svg) | `apps/server/application/receipts.py`; `apps/server/application/orders.py` |
| [Luồng giữ hàng và xuất kho](svg/FLOW_ISSUE.svg) | `apps/server/application/issues.py`; `apps/server/application/reservations.py`; `apps/server/application/picking.py` |
| [Luồng kiểm kê trong phần mềm](svg/FLOW_COUNT.svg) | `apps/server/application/counting.py` |
| [Luồng chuyển kho trong phần mềm](svg/FLOW_TRANSFER.svg) | `apps/server/application/transfers.py`; `apps/server/application/transfer_stock.py` |
| [Luồng nhập dữ liệu từ tệp](svg/FLOW_IMPORT.svg) | `apps/desktop/views/imports.py`; `apps/server/application/imports.py`; `apps/server/application/import_jobs.py` |
| [Tải lại giao diện và đóng ứng dụng](svg/FLOW_LIFECYCLE.svg) | `apps/desktop/views/shell.py`; `apps/desktop/lifecycle.py`; `apps/desktop/__main__.py` |
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
| [ERD hiện hành · app_user](svg/ERD_app_user.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · approval_policy](svg/ERD_approval_policy.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · approval_policy_step](svg/ERD_approval_policy_step.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · approval_request](svg/ERD_approval_request.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · approval_step](svg/ERD_approval_step.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · audit_event](svg/ERD_audit_event.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · auth_challenge](svg/ERD_auth_challenge.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · auth_contact](svg/ERD_auth_contact.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · auth_contact_challenge](svg/ERD_auth_contact_challenge.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · auth_delivery](svg/ERD_auth_delivery.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · auth_google_flow](svg/ERD_auth_google_flow.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · auth_google_identity](svg/ERD_auth_google_identity.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · auth_password_reset](svg/ERD_auth_password_reset.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · auth_recovery_code](svg/ERD_auth_recovery_code.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · auth_self_reset](svg/ERD_auth_self_reset.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · auth_session](svg/ERD_auth_session.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · auth_throttle](svg/ERD_auth_throttle.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · auth_token](svg/ERD_auth_token.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · barcode](svg/ERD_barcode.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · client_release](svg/ERD_client_release.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · consignment_agreement](svg/ERD_consignment_agreement.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · consignment_receipt](svg/ERD_consignment_receipt.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · consignment_receipt_line](svg/ERD_consignment_receipt_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · consumer_receipt](svg/ERD_consumer_receipt.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · count_assignment](svg/ERD_count_assignment.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · count_decision](svg/ERD_count_decision.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · count_empty_confirmation](svg/ERD_count_empty_confirmation.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · count_execution](svg/ERD_count_execution.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · count_line](svg/ERD_count_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · count_location_lock](svg/ERD_count_location_lock.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · count_observation](svg/ERD_count_observation.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · count_scope](svg/ERD_count_scope.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · count_session](svg/ERD_count_session.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · count_submission](svg/ERD_count_submission.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · custom_field_binding](svg/ERD_custom_field_binding.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · custom_field_change](svg/ERD_custom_field_change.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · custom_field_definition](svg/ERD_custom_field_definition.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · custom_field_revision](svg/ERD_custom_field_revision.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · custom_field_schema](svg/ERD_custom_field_schema.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · document](svg/ERD_document.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · document_assignment](svg/ERD_document_assignment.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · document_attachment](svg/ERD_document_attachment.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · document_line](svg/ERD_document_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · document_link](svg/ERD_document_link.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · export_job](svg/ERD_export_job.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · export_task](svg/ERD_export_task.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · fulfillment_consumption](svg/ERD_fulfillment_consumption.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · grant_request](svg/ERD_grant_request.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · idempotency_record](svg/ERD_idempotency_record.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · import_document_source](svg/ERD_import_document_source.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · import_file](svg/ERD_import_file.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · import_job](svg/ERD_import_job.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · import_row](svg/ERD_import_row.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · import_task](svg/ERD_import_task.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · inventory_transaction](svg/ERD_inventory_transaction.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · issue_document](svg/ERD_issue_document.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · location](svg/ERD_location.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · lot](svg/ERD_lot.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · mfa_factor](svg/ERD_mfa_factor.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · move_line](svg/ERD_move_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · opening_document](svg/ERD_opening_document.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · opening_line](svg/ERD_opening_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · organization](svg/ERD_organization.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · outbox_event](svg/ERD_outbox_event.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · package](svg/ERD_package.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · package_line](svg/ERD_package_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · partner](svg/ERD_partner.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · period_reopen_confirmation](svg/ERD_period_reopen_confirmation.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · permission](svg/ERD_permission.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · pick_task](svg/ERD_pick_task.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · print_attempt](svg/ERD_print_attempt.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · print_job](svg/ERD_print_job.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · print_task](svg/ERD_print_task.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · product](svg/ERD_product.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · product_category](svg/ERD_product_category.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · product_image](svg/ERD_product_image.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · product_uom](svg/ERD_product_uom.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · quality_decision](svg/ERD_quality_decision.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · reference_price](svg/ERD_reference_price.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · report_request_guard](svg/ERD_report_request_guard.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · report_snapshot](svg/ERD_report_snapshot.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · report_snapshot_row](svg/ERD_report_snapshot_row.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · reservation](svg/ERD_reservation.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · reservation_consumption](svg/ERD_reservation_consumption.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · return_document](svg/ERD_return_document.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · return_line](svg/ERD_return_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · reversal_document](svg/ERD_reversal_document.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · reversal_line](svg/ERD_reversal_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · role](svg/ERD_role.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · role_permission](svg/ERD_role_permission.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · serial](svg/ERD_serial.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · serial_position](svg/ERD_serial_position.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · serial_warranty_record](svg/ERD_serial_warranty_record.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · stock_balance](svg/ERD_stock_balance.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · stock_item](svg/ERD_stock_item.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · stock_move](svg/ERD_stock_move.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · stock_owner](svg/ERD_stock_owner.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · stock_period](svg/ERD_stock_period.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · stored_file](svg/ERD_stored_file.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · transfer_adjustment](svg/ERD_transfer_adjustment.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · transfer_discrepancy](svg/ERD_transfer_discrepancy.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · transfer_line](svg/ERD_transfer_line.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · transfer_move](svg/ERD_transfer_move.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · uom](svg/ERD_uom.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · user_avatar](svg/ERD_user_avatar.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · user_role_grant](svg/ERD_user_role_grant.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · warehouse](svg/ERD_warehouse.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
| [ERD hiện hành · worker_status](svg/ERD_worker_status.svg) | `02_CSDL/current/schema.json`; `migrations/001_schema.sql … 026_user_avatar.sql` |
