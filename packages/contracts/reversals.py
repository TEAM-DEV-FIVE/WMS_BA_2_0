from datetime import date
from uuid import UUID

from pydantic import Field

from packages.contracts import Contract, PositiveQuantity
from packages.contracts.master_data import Reason
from packages.contracts.orders import OrderAction, OrderResult, OrderView


class ReversalInput(Contract):
    source_transaction_id: UUID
    source_version: int = Field(ge=1, strict=True)
    business_date: date
    reason: Reason


class ReversalUpdate(ReversalInput):
    expected_version: int = Field(ge=1, strict=True)


class ReversalPost(OrderAction):
    execution_key: UUID


class ReversalResult(OrderResult):
    source_transaction_id: UUID
    transaction_id: UUID | None = None


class ReversalLine(Contract):
    source_move_id: UUID
    stock_item_id: UUID
    product_id: UUID
    sku: str
    owner_id: UUID
    owner_code: str
    consignment_id: UUID | None
    lot_code: str | None
    serial_code: str | None
    source_location_id: UUID
    source_code: str
    source_kind: str
    destination_location_id: UUID
    destination_code: str
    destination_kind: str
    quantity_base: PositiveQuantity
    base_uom_id: UUID


class ReversalEffect(Contract):
    stock_item_id: UUID
    location_id: UUID
    location_code: str
    on_hand: str
    reserved: str
    delta: str
    projected_on_hand: str


class ReversalBlock(Contract):
    code: str
    message: str


class ReversalSource(Contract):
    id: UUID
    document_id: UUID
    document_number: str
    document_kind: str
    source_version: int
    warehouse_id: UUID
    operation: str
    business_date: date
    reversal_transaction_id: UUID | None


class ReversalSourcePage(Contract):
    items: list[ReversalSource]
    next_after: UUID | None


class ReversalPreview(Contract):
    source: ReversalSource
    business_date: date
    warehouse_ids: list[UUID]
    eligible: bool
    blockers: list[ReversalBlock]
    plan: list[ReversalLine]
    effects: list[ReversalEffect]


class ReversalView(OrderView):
    source_transaction_id: UUID
    source_document_id: UUID
    source_version: int
    reversal_reason: str
    transaction_id: UUID | None
    plan: list[ReversalLine]
    preview: ReversalPreview


class ReversalOperation(Contract):
    command: str
    result: ReversalResult
