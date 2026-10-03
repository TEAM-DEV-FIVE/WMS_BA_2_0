from apps.server.application.master_data import one
from apps.server.application.openings import OpeningService
from apps.server.application.receipts import EXTERNAL
from apps.server.domain.errors import DomainError
from packages.contracts.consignments import ConsignmentReceiptView


class ConsignmentReceiptService(OpeningService):
    """Approved full receipt under a custody agreement, independent of purchase orders.

    No cutover: warehouse SHARE participates in the same lock as PO receipt;
    opening's exclusive warehouse lock still closes cutover atomically.
    """

    kind, command_prefix, number_prefix = "RECEIPT", "consignment_receipt", "CSR"
    permission_prefix = "receipt"
    metadata_table, plan_table = "consignment_receipt", "consignment_receipt_line"
    reference_field = "delivery_reference"
    source_location, source_kind, operation_code = EXTERNAL, "EXTERNAL", "RECEIVE"
    physical_kinds, consignor_only = {"RECEIVING", "QUARANTINE"}, True
    view_model = ConsignmentReceiptView

    def cutover(self, c, warehouse_id):
        pass  # Normal receipt may follow earlier stock; all other inbound checks remain mandatory.

    def may_post(self, auth, doc):
        super().may_post(auth, doc)
        if doc["created_by"] != auth.principal.user_id and not one(
            auth.connection,
            "SELECT id FROM wms.document_assignment WHERE document_id=:id AND user_id=:user",
            id=doc["id"],
            user=auth.principal.user_id,
        ):
            raise DomainError("FORBIDDEN", "Chỉ người lập hoặc được giao mới ghi sổ nhận ký gửi.")
