from datetime import date, datetime
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from packages.contracts import Contract, PositiveQuantity
from packages.contracts.master_data import Reason
from packages.contracts.orders import OrderAction, OrderResult, OrderView


class IssueLineInput(Contract):
    source_line_id: UUID
    quantity_base: PositiveQuantity


class IssueInput(Contract):
    source_order_id: UUID
    business_date: date
    reason: Reason
    lines: list[IssueLineInput] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_sources(self):
        if len({line.source_line_id for line in self.lines}) != len(self.lines):
            raise ValueError("Use one issue line per SO line")
        return self


class IssueUpdate(IssueInput):
    expected_version: int = Field(ge=1, strict=True)


class Allocation(Contract):
    document_line_id: UUID
    stock_item_id: UUID
    location_id: UUID
    quantity_base: PositiveQuantity


class AllocationView(Allocation):
    sku: str
    location_code: str
    owner_id: UUID
    lot_code: str | None
    serial_code: str | None
    expires_on: date | None


class ReservationPlan(Contract):
    document_id: UUID
    version: int
    lines: list[AllocationView]


class ReserveInput(OrderAction):
    lines: list[Allocation] = Field(min_length=1, max_length=500)
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def unique_allocations(self):
        keys = [(line.document_line_id, line.stock_item_id, line.location_id) for line in self.lines]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate allocation")
        return self


class ReservationQuantity(Contract):
    reservation_id: UUID
    quantity_base: PositiveQuantity


class ReleaseInput(OrderAction):
    lines: list[ReservationQuantity] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_reservations(self):
        if len({line.reservation_id for line in self.lines}) != len(self.lines):
            raise ValueError("Duplicate reservation")
        return self


class IssuePost(ReleaseInput):
    execution_key: UUID


class ReservationView(Contract):
    id: UUID
    document_line_id: UUID
    stock_item_id: UUID
    location_id: UUID
    location_code: str
    owner_id: UUID
    sku: str
    lot_code: str | None
    serial_code: str | None
    quantity: str
    consumed: str
    released: str
    remaining_base: str
    expires_at: datetime | None
    expired: bool


class IssueView(OrderView):
    source_order_id: UUID
    source_line_ids: dict[UUID, UUID]
    reservations: list[ReservationView]


class IssuePostResult(OrderResult):
    transaction_id: UUID
    source_order_id: UUID
    source_order_version: int
    source_order_status: str


class IssueOperation(Contract):
    operation_status: str = "COMMITTED"
    command: str
    result: dict
