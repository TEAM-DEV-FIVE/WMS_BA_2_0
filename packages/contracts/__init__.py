"""Transport-only types shared by server and desktop; no persistence or secrets."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints


def positive(value: str) -> str:
    if Decimal(value) <= 0:
        raise ValueError("Quantity must be positive")
    return value

PositiveQuantity = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^(?:0|[1-9][0-9]{0,13})(?:\.[0-9]{1,6})?$",
    ),
    AfterValidator(positive),
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldError(Contract):
    field: str
    code: str
    message: str
    line_id: str | None = None


class Error(Contract):
    code: str
    message: str
    request_id: UUID
    retryable: bool = False
    field_errors: list[FieldError] = Field(default_factory=list)


class Health(Contract):
    status: Literal["ok", "ready"]
    service: Literal["wms-api"] = "wms-api"
    version: str = "0.1.0"


class CommandEnvelope(Contract):
    expected_version: int = Field(ge=1, strict=True)
    execution_key: UUID


class Result(Contract):
    id: UUID
    status: str
    request_id: UUID
    version: int | None = Field(default=None, ge=1)
    transaction_id: UUID | None = None
