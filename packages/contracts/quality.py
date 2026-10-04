from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import StringConstraints, model_validator

from packages.contracts import Contract
from packages.contracts.orders import OrderAction

NonnegativeQuantity = Annotated[str, StringConstraints(strict=True, pattern=r"^(?:0|[1-9][0-9]{0,13})(?:\.[0-9]{1,6})?$")]


class QualityInput(OrderAction):
    accepted_base: NonnegativeQuantity
    rejected_base: NonnegativeQuantity

    @model_validator(mode="after")
    def nonempty(self):
        if Decimal(self.accepted_base) + Decimal(self.rejected_base) <= 0:
            raise ValueError("A quality decision needs positive quantity")
        return self


class QualitySource(Contract):
    id: UUID
    receipt_id: UUID
    receipt_number: str
    version: int
    stock_item_id: UUID
    product_id: UUID
    sku: str
    tracking: str
    lot_code: str | None
    serial_code: str | None
    owner_id: UUID
    owner_code: str
    consignment_id: UUID | None
    source_location_id: UUID
    location_code: str
    received_base: str
    decided_base: str
    remaining_base: str


class QualitySourcePage(Contract):
    items: list[QualitySource]
    next_after: UUID | None


class QualityDecision(Contract):
    id: UUID
    receipt_move_id: UUID
    quantity: str
    result: Literal["ACCEPT", "REJECT"]
    reason: str
    decided_by: UUID
    decided_at: datetime
    moved_base: str
    remaining_base: str
    followup_document_id: UUID | None


class QualityHistory(Contract):
    source: QualitySource
    items: list[QualityDecision]
    next_after: UUID | None
    allowed_actions: list[str]


class QualityResult(Contract):
    id: UUID
    receipt_move_id: UUID
    warehouse_id: UUID
    version: int
    status: Literal["DECIDED"] = "DECIDED"
    decision_ids: list[UUID]
    request_id: UUID
