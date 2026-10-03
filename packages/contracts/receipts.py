from datetime import date
from uuid import UUID

from pydantic import Field, model_validator

from packages.contracts import Contract, PositiveQuantity
from packages.contracts.master_data import Reason
from packages.contracts.orders import OrderAction, OrderResult, OrderView


class ReceiptLineInput(Contract):
    source_line_id: UUID
    quantity_base: PositiveQuantity
    destination_location_id: UUID
    lot_code: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^\S(?:.*\S)?$")
    serial_code: str | None = Field(default=None, min_length=1, max_length=160, pattern=r"^\S(?:.*\S)?$")
    manufactured_on: date | None = None
    expires_on: date | None = None


class ReceiptInput(Contract):
    source_order_id: UUID
    business_date: date
    lines: list[ReceiptLineInput] = Field(min_length=1, max_length=200)
    reason: Reason


class ReceiptUpdate(ReceiptInput):
    expected_version: int = Field(ge=1, strict=True)


class ReceiptPlan(ReceiptLineInput):
    document_line_id: UUID
    location_code: str
    tracking: str


class ReceiptView(OrderView):
    source_order_id: UUID
    plan: list[ReceiptPlan]


class PostLine(Contract):
    document_line_id: UUID
    quantity_base: PositiveQuantity


class ReceiptPost(OrderAction):
    execution_key: UUID
    lines: list[PostLine] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_lines(self):
        if len({line.document_line_id for line in self.lines}) != len(self.lines):
            raise ValueError("Duplicate receipt line")
        return self


class ReceiptPostResult(OrderResult):
    transaction_id: UUID
    source_order_id: UUID
    source_order_version: int
    source_order_status: str


class OperationView(Contract):
    operation_status: str = "COMMITTED"
    id: UUID
    status: str
    version: int
    request_id: UUID
    transaction_id: UUID
