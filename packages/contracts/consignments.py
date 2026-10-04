"""Consignment delivery is an inbound custody receipt, with no purchase/sale terms."""

from datetime import date
from uuid import UUID

from pydantic import Field

from packages.contracts import Contract
from packages.contracts.master_data import Reason
from packages.contracts.openings import OpeningLineInput, OpeningPlan
from packages.contracts.orders import OrderView


class ConsignmentReceiptInput(Contract):
    warehouse_id: UUID
    batch_key: UUID
    business_date: date
    delivery_reference: Reason
    lines: list[OpeningLineInput] = Field(min_length=1, max_length=200)
    reason: Reason


class ConsignmentReceiptUpdate(ConsignmentReceiptInput):
    expected_version: int = Field(ge=1, strict=True)


class ConsignmentReceiptView(OrderView):
    batch_key: UUID
    delivery_reference: str
    plan: list[OpeningPlan]


class IncomingOwner(Contract):
    id: UUID
    owner_id: UUID
    owner_code: str
    owner_name: str
    consignment_id: UUID | None
    consignment_code: str | None
