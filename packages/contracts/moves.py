from datetime import date
from uuid import UUID

from pydantic import Field

from packages.contracts import Contract, PositiveQuantity
from packages.contracts.master_data import Reason
from packages.contracts.orders import OrderAction, OrderResult, OrderView


class MoveLineInput(Contract):
    stock_item_id: UUID
    source_location_id: UUID
    destination_location_id: UUID
    quantity_base: PositiveQuantity
    quality_decision_id: UUID | None = None


class MoveInput(Contract):
    warehouse_id: UUID
    business_date: date
    reason: Reason
    lines: list[MoveLineInput] = Field(min_length=1, max_length=200)


class MoveUpdate(MoveInput):
    expected_version: int = Field(ge=1, strict=True)


class MovePlan(MoveLineInput):
    document_line_id: UUID
    source_code: str
    destination_code: str
    lot_code: str | None
    serial_code: str | None


class MoveView(OrderView):
    plan: list[MovePlan]


class MovePost(OrderAction):
    execution_key: UUID


class MovePostResult(OrderResult):
    transaction_id: UUID


class MoveLocation(Contract):
    id: UUID
    code: str
    name: str
    kind: str


class MoveLocationPage(Contract):
    items: list[MoveLocation]
    next_after: UUID | None


class MoveStock(Contract):
    id: UUID
    stock_item_id: UUID
    source_location_id: UUID
    source_code: str
    source_kind: str
    sku: str
    tracking: str
    lot_code: str | None
    serial_code: str | None
    owner_code: str
    owner_id: UUID
    consignment_id: UUID | None
    on_hand: str
    reserved: str
    movable_base: str
    eligible_base: str
    available_base: str
    frozen: bool


class MoveStockPage(Contract):
    items: list[MoveStock]
    next_after: UUID | None
