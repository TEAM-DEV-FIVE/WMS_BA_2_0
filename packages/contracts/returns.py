from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field

from packages.contracts import Contract, PositiveQuantity
from packages.contracts.master_data import Reason
from packages.contracts.orders import OrderAction, OrderResult, OrderView

ReturnKind = Literal["CUSTOMER_RETURN", "SUPPLIER_RETURN"]


class ReturnLineInput(Contract):
    source_move_id: UUID
    location_id: UUID
    quantity_base: PositiveQuantity


class ReturnInput(Contract):
    kind: ReturnKind
    source_document_id: UUID
    business_date: date
    reason: Reason
    lines: list[ReturnLineInput] = Field(min_length=1, max_length=200)


class ReturnUpdate(ReturnInput):
    expected_version: int = Field(ge=1, strict=True)


class ReturnPlan(ReturnLineInput):
    document_line_id: UUID
    stock_item_id: UUID
    location_code: str
    lot_code: str | None
    serial_code: str | None
    serial_id: UUID | None


class ReturnView(OrderView):
    source_document_id: UUID
    source_document_number: str
    plan: list[ReturnPlan]


class ReturnSource(Contract):
    id: UUID
    document_id: UUID
    document_number: str
    document_kind: str
    source_line_id: UUID
    warehouse_id: UUID
    partner_id: UUID | None
    stock_item_id: UUID
    sku: str
    tracking: str
    base_uom_code: str
    owner_id: UUID
    owner_code: str
    consignment_id: UUID | None
    lot_code: str | None
    serial_code: str | None
    serial_id: UUID | None
    posted_base: str
    returned_base: str
    remaining_base: str
    returnable: bool
    blocked_reason: str | None


class ReturnSourcePage(Contract):
    items: list[ReturnSource]
    next_after: UUID | None


class ReturnPost(OrderAction):
    execution_key: UUID


class ReturnPostResult(OrderResult):
    transaction_id: UUID
