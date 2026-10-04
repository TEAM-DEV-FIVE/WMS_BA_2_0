"""Stable report snapshots; quantities/prices travel as decimal strings."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from packages.contracts import Contract

ReportCode = Literal["R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08"]


class ReportCriteria(Contract):
    warehouse_id: UUID
    location_ids: list[UUID] = Field(default_factory=list, max_length=200)
    owner_id: UUID | None = None
    product_id: UUID | None = None
    business_from: date | None = None
    business_to: date | None = None
    posted_from: datetime | None = None
    posted_to: datetime | None = None
    effective_on: date | None = None
    include_price: bool = False
    sort_by: Literal["default", "sku", "location_code", "owner_code"] = "default"
    descending: bool = False

    @model_validator(mode="after")
    def ranges(self):
        for name in ["posted_from", "posted_to"]:
            value = getattr(self, name)
            if value and value.utcoffset() is None:
                raise ValueError("Posted time requires timezone")
        for start, end in [(self.business_from, self.business_to), (self.posted_from, self.posted_to)]:
            if start and end and start > end:
                raise ValueError("Invalid date range")
        if len(set(self.location_ids)) != len(self.location_ids):
            raise ValueError("Duplicate locations")
        return self


class ReportSnapshot(Contract):
    id: UUID
    report_code: ReportCode
    criteria: ReportCriteria
    created_at: datetime
    expires_at: datetime
    row_count: int
    columns: list[str]
    sha256: str


class ReportPage(Contract):
    snapshot: ReportSnapshot
    items: list[dict]
    next_after: int | None


class ExportCreate(Contract):
    snapshot_id: UUID
    format: Literal["csv", "xlsx"]


class ExportAction(Contract):
    expected_version: int = Field(ge=1, strict=True)


class ExportView(Contract):
    id: UUID
    snapshot_id: UUID
    report_code: ReportCode
    format: Literal["csv", "xlsx"]
    status: Literal["QUEUED", "RUNNING", "READY", "FAILED", "CANCELLED"]
    version: int
    generation: int
    created_at: datetime
    expires_at: datetime
    error_code: str | None
    sha256: str | None = None
    size_bytes: int | None = None
