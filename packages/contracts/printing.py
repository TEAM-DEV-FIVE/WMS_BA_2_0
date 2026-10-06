"""Versioned print snapshots and explicit, at-most-once spool claims."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from packages.contracts import Contract

Template = Literal["RECEIPT", "ISSUE", "TRANSFER", "COUNT", "PRODUCT_LABEL", "LOCATION_LABEL"]
Paper = Literal["A4", "A5", "100x50", "80x40"]
SafeText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=r"^[^\x00-\x1f\x7f]+$"),
]


class PrintCreate(Contract):
    template: Template
    source_id: UUID
    warehouse_id: UUID
    expected_version: int = Field(ge=1, strict=True)
    paper: Paper = "A4"
    include_price: bool = False
    serial_id: UUID | None = None

    @model_validator(mode="after")
    def compatible(self):
        label = self.template.endswith("LABEL")
        if label != (self.paper in {"100x50", "80x40"}):
            raise ValueError("Paper must match the selected template")
        if self.serial_id and self.template != "PRODUCT_LABEL":
            raise ValueError("Serial only applies to product labels")
        if self.include_price and self.template not in {"RECEIPT", "ISSUE", "TRANSFER"}:
            raise ValueError("This template has no price")
        return self


class PrintAction(Contract):
    expected_version: int = Field(ge=1, strict=True)
    reason: SafeText


class SpoolBegin(PrintAction):
    attempt_id: UUID
    printer: SafeText
    driver: Literal["WINDOWS_GDI", "CUPS"]
    copies: int = Field(ge=1, le=20, strict=True)


class SpoolResult(Contract):
    expected_version: int = Field(ge=1, strict=True)
    attempt_id: UUID
    outcome: Literal["SUBMITTED", "FAILED", "UNKNOWN"]
    spool_id: SafeText | None = None
    error_code: Literal["SPOOL_UNAVAILABLE", "SPOOL_TIMEOUT", "SPOOL_ERROR", "SESSION_CHANGED"] | None = None


class PrintJob(Contract):
    id: UUID
    template: Template
    source_id: UUID
    source_version: int
    warehouse_id: UUID
    paper: Paper
    include_price: bool
    template_version: int
    status: Literal["QUEUED", "RENDERING", "READY", "FAILED", "CANCELLED"]
    version: int
    generation: int
    created_at: datetime
    expires_at: datetime
    sha256: str | None = None
    size_bytes: int | None = None
    error_code: str | None = None
    attempt: dict | None = None


class ScanInput(Contract):
    flow: Literal["RECEIPT", "PICK", "ISSUE", "TRANSFER", "COUNT"]
    source_id: UUID
    expected_version: int = Field(ge=1, strict=True)
    code: Annotated[str, StringConstraints(min_length=1, max_length=160, pattern=r"^[^\x00-\x1f\x7f]+$")]
    quantity: Annotated[str, StringConstraints(pattern=r"^(0|[1-9][0-9]{0,12})(\.[0-9]{1,6})?$")] = "1"
