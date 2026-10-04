from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from packages.contracts import Contract, PositiveQuantity
from packages.contracts.master_data import Reason
from packages.contracts.orders import ApprovalView, OrderAction, OrderResult, OrderSummary


class TransferLineInput(Contract):
    stock_item_id: UUID
    source_location_id: UUID
    quantity_base: PositiveQuantity


class TransferInput(Contract):
    warehouse_id: UUID
    destination_warehouse_id: UUID
    business_date: date
    reason: Reason
    lines: list[TransferLineInput] = Field(min_length=1, max_length=200)


class TransferUpdate(TransferInput):
    expected_version: int = Field(ge=1, strict=True)


class TransferDispatch(OrderAction):
    execution_key: UUID
    evidence_ref: Reason


class TransferReceiveLine(Contract):
    dispatch_move_id: UUID
    destination_location_id: UUID
    quantity_base: PositiveQuantity
    disposition: Literal["GOOD", "DAMAGED"] = "GOOD"


class TransferReceive(TransferDispatch):
    business_date: date
    lines: list[TransferReceiveLine] = Field(min_length=1, max_length=200)


class TransferDiscrepancy(OrderAction):
    dispatch_move_id: UUID
    kind: Literal["MISSING", "DAMAGED"]
    quantity_base: PositiveQuantity
    evidence_ref: Reason


class TransferLossInput(OrderAction):
    discrepancy_id: UUID
    quantity_base: PositiveQuantity
    business_date: date


class TransferResult(OrderResult):
    destination_warehouse_id: UUID
    source_transfer_id: UUID | None = None
    discrepancy_id: UUID | None = None


class TransferPostResult(TransferResult):
    transaction_id: UUID
    operation: Literal["DISPATCH", "ARRIVE", "ADJUST"]


class TransferPlan(Contract):
    document_line_id: UUID
    stock_item_id: UUID
    source_location_id: UUID | None
    source_code: str | None
    sku: str
    owner_id: UUID
    owner_code: str
    consignment_id: UUID | None
    lot_code: str | None
    serial_code: str | None
    quantity_base: str


class TransferSource(Contract):
    dispatch_move_id: UUID
    document_line_id: UUID
    stock_item_id: UUID
    sku: str
    owner_code: str
    lot_code: str | None
    serial_code: str | None
    dispatched_base: str
    received_base: str
    lost_base: str
    remaining_base: str


class TransferEvidence(Contract):
    id: UUID
    dispatch_move_id: UUID
    kind: str
    quantity_base: str
    evidence_ref: str
    recorded_by: UUID
    recorded_at: datetime


class TransferHistory(Contract):
    id: UUID
    document_id: UUID
    transaction_id: UUID
    dispatch_move_id: UUID | None
    operation: str
    disposition: str
    quantity_base: str
    evidence_ref: str
    posted_at: datetime
    posted_by: UUID
    destination_code: str | None


class TransferHistoryPage(Contract):
    items: list[TransferHistory]
    next_after: UUID | None


class TransferView(OrderSummary):
    destination_warehouse_id: UUID
    transit_location_id: UUID
    source_transfer_id: UUID | None
    discrepancy_id: UUID | None
    reason: str | None
    plan: list[TransferPlan]
    sources: list[TransferSource]
    discrepancies: list[TransferEvidence]
    adjustments: list[OrderSummary]
    approvals: list[ApprovalView]
    assigned_user_ids: list[UUID]
    allowed_actions: list[str]


class TransferAssignee(Contract):
    id: UUID
    username: str
    display_name: str


class TransferAssigneePage(Contract):
    items: list[TransferAssignee]
    next_after: UUID | None


class TransferEvidencePage(Contract):
    items: list[TransferEvidence]
    next_after: UUID | None
