"""Blind count responses are separate contracts: quantities never become optional fields."""
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from packages.contracts import Contract
from packages.contracts.master_data import Reason
from packages.contracts.orders import OrderAction
from packages.contracts.quality import NonnegativeQuantity


class CountScope(Contract):
    location_id: UUID
    user_ids: list[UUID] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def unique_users(self):
        if len(set(self.user_ids)) != len(self.user_ids):
            raise ValueError("Duplicate counters")
        return self


class CountInput(Contract):
    warehouse_id: UUID
    business_date: date
    reason: Reason
    scope: list[CountScope] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_locations(self):
        if len({s.location_id for s in self.scope}) != len(self.scope):
            raise ValueError("Duplicate locations")
        return self


class CountObservationInput(OrderAction):
    line_id: UUID
    round_no: Annotated[int, Field(strict=True, ge=1, le=100)]
    quantity: NonnegativeQuantity
    scan_event_key: UUID


class CountExtraInput(OrderAction):
    location_id: UUID
    product_id: UUID
    owner_id: UUID
    consignment_id: UUID | None = None
    lot_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    serial_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)] | None = None
    expires_on: date | None = None


class CountDecisionInput(OrderAction):
    decision: Literal["APPROVE", "REJECT"]


class CountEmptyInput(OrderAction):
    location_id: UUID


class CountPost(OrderAction):
    execution_key: UUID


class CountResult(Contract):
    id: UUID
    warehouse_id: UUID
    number: str
    status: Literal["DRAFT", "FROZEN", "COUNTED", "SUBMITTED", "POSTED", "CANCELLED"]
    version: int
    request_id: UUID
    adjustment_document_id: UUID | None = None
    transaction_id: UUID | None = None
    execution_key: UUID | None = None


class CountSummary(Contract):
    id: UUID
    warehouse_id: UUID
    number: str
    status: str
    version: int
    business_date: date


class CountPage(Contract):
    items: list[CountSummary]
    next_after: UUID | None


class BlindLine(Contract):
    id: UUID
    stock_item_id: UUID
    location_id: UUID
    location_code: str
    sku: str
    tracking: str
    owner_code: str
    consignment_id: UUID | None
    lot_code: str | None
    serial_code: str | None
    next_round: int
    can_count: bool


class CountView(CountSummary):
    reason: str
    mode: Literal["BLIND"] = "BLIND"
    lines: list[BlindLine]
    scope: list["CountScopeView"]
    allowed_actions: list[str]


class ObservationView(Contract):
    round_no: int
    quantity: str
    counted_by: UUID
    counted_at: datetime
    reason: str


class ReviewLine(BlindLine):
    snapshot_quantity: str
    approved_quantity: str | None
    delta: str | None
    observations: list[ObservationView]


class CountReview(CountSummary):
    reason: str
    mode: Literal["REVIEW"] = "REVIEW"
    lines: list[ReviewLine]
    scope: list["CountScopeView"]
    decisions: list[dict]
    empty_confirmations: list[dict]
    allowed_actions: list[str]


class CountCatalogItem(Contract):
    id: UUID
    code: str
    name: str


class CountScopeView(Contract):
    location_id: UUID
    user_ids: list[UUID]


class CountCatalog(Contract):
    items: list[CountCatalogItem]
    next_after: UUID | None
