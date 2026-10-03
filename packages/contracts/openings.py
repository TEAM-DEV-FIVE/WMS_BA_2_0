from datetime import date
from uuid import UUID

from pydantic import Field

from packages.contracts import Contract, PositiveQuantity
from packages.contracts.master_data import Reason
from packages.contracts.orders import OrderAction, OrderResult, OrderView


class OpeningLineInput(Contract):
    product_id: UUID
    quantity_base: PositiveQuantity
    owner_id: UUID
    destination_location_id: UUID
    lot_code: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^\S(?:.*\S)?$")
    serial_code: str | None = Field(default=None, min_length=1, max_length=160, pattern=r"^\S(?:.*\S)?$")
    manufactured_on: date | None = None
    expires_on: date | None = None


class OpeningInput(Contract):
    warehouse_id: UUID
    batch_key: UUID
    business_date: date
    signed_count_reference: Reason
    lines: list[OpeningLineInput] = Field(min_length=1, max_length=200)
    reason: Reason


class OpeningUpdate(OpeningInput):
    expected_version: int = Field(ge=1, strict=True)


class OpeningPlan(OpeningLineInput):
    document_line_id: UUID
    location_code: str
    tracking: str


class OpeningView(OrderView):
    batch_key: UUID
    signed_count_reference: str
    plan: list[OpeningPlan]


class OpeningPost(OrderAction):
    execution_key: UUID


class OpeningPostResult(OrderResult):
    transaction_id: UUID
