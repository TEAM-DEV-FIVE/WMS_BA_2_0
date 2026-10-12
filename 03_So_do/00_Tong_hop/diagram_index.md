> **Lịch sử thiết kế cơ sở.** Khi mô tả ứng dụng hiện tại, dùng [mục lục mới](../Hien_hanh/index.md) và [PDF hiện hành](../Hien_hanh/WMS_Hien_hanh.pdf).

# Mục lục sơ đồ

| Trang | Mã | Tên |
|---|---|---|
|1|ERD_01_organization|ERD vật lý / master / organization|
|2|ERD_02_app_user|ERD vật lý / iam / app_user|
|3|ERD_03_role|ERD vật lý / iam / role|
|4|ERD_04_permission|ERD vật lý / iam / permission|
|5|ERD_05_role_permission|ERD vật lý / iam / role_permission|
|6|ERD_06_user_role_grant|ERD vật lý / iam / user_role_grant|
|7|ERD_07_auth_session|ERD vật lý / iam / auth_session|
|8|ERD_08_mfa_factor|ERD vật lý / iam / mfa_factor|
|9|ERD_09_warehouse|ERD vật lý / master / warehouse|
|10|ERD_10_location|ERD vật lý / master / location|
|11|ERD_11_uom|ERD vật lý / master / uom|
|12|ERD_12_product_category|ERD vật lý / master / product_category|
|13|ERD_13_product|ERD vật lý / master / product|
|14|ERD_14_product_uom|ERD vật lý / master / product_uom|
|15|ERD_15_barcode|ERD vật lý / master / barcode|
|16|ERD_16_partner|ERD vật lý / master / partner|
|17|ERD_17_lot|ERD vật lý / inventory / lot|
|18|ERD_18_serial|ERD vật lý / inventory / serial|
|19|ERD_19_stock_item|ERD vật lý / inventory / stock_item|
|20|ERD_20_reference_price|ERD vật lý / master / reference_price|
|21|ERD_21_document|ERD vật lý / documents / document|
|22|ERD_22_document_line|ERD vật lý / documents / document_line|
|23|ERD_23_document_link|ERD vật lý / documents / document_link|
|24|ERD_24_document_assignment|ERD vật lý / documents / document_assignment|
|25|ERD_25_inventory_transaction|ERD vật lý / inventory / inventory_transaction|
|26|ERD_26_stock_move|ERD vật lý / inventory / stock_move|
|27|ERD_27_stock_balance|ERD vật lý / inventory / stock_balance|
|28|ERD_28_serial_position|ERD vật lý / inventory / serial_position|
|29|ERD_29_reservation|ERD vật lý / fulfillment / reservation|
|30|ERD_30_pick_task|ERD vật lý / fulfillment / pick_task|
|31|ERD_31_reservation_consumption|ERD vật lý / fulfillment / reservation_consumption|
|32|ERD_32_package|ERD vật lý / fulfillment / package|
|33|ERD_33_package_line|ERD vật lý / fulfillment / package_line|
|34|ERD_34_quality_decision|ERD vật lý / fulfillment / quality_decision|
|35|ERD_35_approval_policy|ERD vật lý / approval / approval_policy|
|36|ERD_36_approval_policy_step|ERD vật lý / approval / approval_policy_step|
|37|ERD_37_approval_request|ERD vật lý / approval / approval_request|
|38|ERD_38_approval_step|ERD vật lý / approval / approval_step|
|39|ERD_39_stock_period|ERD vật lý / counting / stock_period|
|40|ERD_40_count_session|ERD vật lý / counting / count_session|
|41|ERD_41_count_location_lock|ERD vật lý / counting / count_location_lock|
|42|ERD_42_count_assignment|ERD vật lý / counting / count_assignment|
|43|ERD_43_count_line|ERD vật lý / counting / count_line|
|44|ERD_44_count_observation|ERD vật lý / counting / count_observation|
|45|ERD_45_idempotency_record|ERD vật lý / operations / idempotency_record|
|46|ERD_46_outbox_event|ERD vật lý / operations / outbox_event|
|47|ERD_47_consumer_receipt|ERD vật lý / operations / consumer_receipt|
|48|ERD_48_audit_event|ERD vật lý / operations / audit_event|
|49|ERD_49_stored_file|ERD vật lý / operations / stored_file|
|50|ERD_50_document_attachment|ERD vật lý / documents / document_attachment|
|51|ERD_51_product_image|ERD vật lý / master / product_image|
|52|ERD_52_import_job|ERD vật lý / operations / import_job|
|53|ERD_53_import_row|ERD vật lý / operations / import_row|
|54|ERD_54_export_job|ERD vật lý / operations / export_job|
|55|ERD_55_custom_field_definition|ERD vật lý / extension / custom_field_definition|
|56|ERD_56_client_release|ERD vật lý / extension / client_release|
|57|Class_Domain|Class Domain / UML implementation|
|58|Class_Application|Class Application / UML implementation|
|59|Class_Desktop|Class Desktop / UML implementation|
|60|UC_SYSADMIN_1|Quản trị kỹ thuật / Use case|
|61|UC_MASTER_DATA_1|Quản lý danh mục / Use case|
|62|UC_BUYER_1|Mua hàng / Use case|
|63|UC_SELLER_1|Bán hàng / Use case|
|64|UC_RECEIVER_1|Nhân viên nhận / Use case|
|65|UC_RECEIVER_2|Nhân viên nhận / Use case|
|66|UC_PICKER_1|Nhân viên soạn/xuất / Use case|
|67|UC_PICKER_2|Nhân viên soạn/xuất / Use case|
|68|UC_WAREHOUSE_MANAGER_1|Quản lý kho / Use case|
|69|UC_WAREHOUSE_MANAGER_2|Quản lý kho / Use case|
|70|UC_CONTROLLER_1|Kiểm soát/kế toán / Use case|
|71|UC_CONTROLLER_2|Kiểm soát/kế toán / Use case|
|72|UC_DIRECTOR_1|Ban điều hành / Use case|
|73|UC_AUDITOR_1|Kiểm toán / Use case|
|74|UC_COMMON|Người dùng / Tương tác chung|
|75|UC_REL_MFA|Quan hệ use case / extend|
|76|UC_REL_IMPORT|Quan hệ use case / include|
|77|UC_APPROVAL|Duyệt chứng từ theo policy|
|78|ACTOR_GENERALIZATION_1|Tổng quát hóa vai trò người dùng|
|79|ACTOR_GENERALIZATION_2|Tổng quát hóa vai trò người dùng|
|80|ACTOR_GENERALIZATION_3|Tổng quát hóa vai trò người dùng|
|81|document_state|Trạng thái chứng từ|
|82|post_sequence|Trình tự ghi sổ và xử lý timeout|
|83|ER_CONCEPT_DOCUMENT|ERD khái niệm / Chứng từ và hàng hóa|
|84|ER_CONCEPT_STOCK|ERD khái niệm / Vị trí, hàng tồn và phát sinh|
|85|ER_CONCEPT_ACCESS|ERD khái niệm / Tài khoản, vai trò và quyền|
|86|BAM_WMS|Business Activity Model / đề xuất|
|87|P00_ASIS_HYPOTHESIS|As-Is nhận hàng - giả thuyết|
|88|P01_RECEIVE|Nhận hàng|
|89|P02_ISSUE|Xuất hàng|
|90|P03_COUNT|Kiểm kê|
|91|P04_TRANSFER|Chuyển kho|