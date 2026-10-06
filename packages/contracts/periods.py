from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import model_validator

from packages.contracts import Contract
from packages.contracts.master_data import Reason
from packages.contracts.orders import OrderAction


class PeriodInput(Contract):
    warehouse_id: UUID
    starts_on: date
    ends_on: date
    reason: Reason

    @model_validator(mode="after")
    def date_range(self):
        if self.ends_on < self.starts_on:
            raise ValueError("Invalid period range")
        return self


class PeriodReopen(OrderAction):
    confirmation_id: UUID


class PeriodView(Contract):
    id: UUID
    warehouse_id: UUID
    starts_on: date
    ends_on: date
    status: Literal["OPEN", "CLOSED"]
    version: int
    allowed_actions: list[str]
    confirmation_id: UUID | None = None


class PeriodPage(Contract):
    items: list[PeriodView]
    next_after: UUID | None


class PeriodResult(Contract):
    id: UUID
    warehouse_id: UUID
    status: Literal["OPEN", "CLOSED"]
    version: int
    request_id: UUID
    confirmation_id: UUID | None = None
