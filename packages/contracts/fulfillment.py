from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from packages.contracts import Contract, PositiveQuantity
from packages.contracts.issues import ReservationView
from packages.contracts.orders import OrderAction, OrderResult

ScanCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class PickCreate(OrderAction):
    reservation_id: UUID
    assigned_to: UUID
    quantity_base: PositiveQuantity


class FulfillmentAction(OrderAction):
    entity_version: int = Field(ge=1, strict=True)


class PickAssign(FulfillmentAction):
    assigned_to: UUID


class PickConfirm(FulfillmentAction):
    quantity_base: PositiveQuantity
    location_code: ScanCode
    item_code: ScanCode
    trace_code: ScanCode | None = None


class PackLineInput(Contract):
    pick_task_id: UUID
    quantity_base: PositiveQuantity


class PackageCreate(OrderAction):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    lines: list[PackLineInput] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_tasks(self):
        if len({line.pick_task_id for line in self.lines}) != len(self.lines):
            raise ValueError("Use one package line per pick task")
        return self


class PickView(Contract):
    id: UUID
    reservation_id: UUID
    assigned_to: UUID
    assignee_name: str
    target_quantity: str | None
    picked_quantity: str
    consumed_quantity: str
    unpacked_base: str
    status: str
    version: int
    reason: str | None
    allowed_actions: list[str]


class PackLineView(Contract):
    id: UUID
    pick_task_id: UUID | None
    document_line_id: UUID
    stock_item_id: UUID
    quantity: str
    consumed_quantity: str


class PackageView(Contract):
    id: UUID
    code: str
    status: str | None
    version: int
    reason: str | None
    lines: list[PackLineView]
    allowed_actions: list[str]


class FulfillmentView(Contract):
    id: UUID
    warehouse_id: UUID
    number: str
    status: str
    version: int
    source_order_id: UUID
    reservations: list[ReservationView]
    tasks: list[PickView]
    packages: list[PackageView]
    allowed_actions: list[str]


class PickerView(Contract):
    id: UUID
    display_name: str


class PickerPage(Contract):
    items: list[PickerView]
    next_after: UUID | None


class FulfillmentResult(OrderResult):
    entity_id: UUID
    entity_kind: Literal["pick", "package"]
    entity_status: str
    entity_version: int
    assigned_to: UUID | None = None
    quantity_base: str | None = None


class FulfillmentOperation(Contract):
    operation_status: Literal["COMMITTED"] = "COMMITTED"
    command: str
    result: FulfillmentResult
