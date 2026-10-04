"""Versioned, flat descriptive metadata. Never an inventory command language."""

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from packages.contracts import Contract
from packages.contracts.master_data import Reason

EntityType = Literal["PRODUCT", "PO", "SO", "RECEIPT", "OPENING", "ISSUE", "INTERNAL_MOVE",
                     "TRANSFER", "ADJUSTMENT", "CUSTOMER_RETURN", "SUPPLIER_RETURN", "REVERSAL"]
TargetType = Literal["products", "documents"]
Value = StrictStr | StrictInt | StrictBool | None
Code = Annotated[str, Field(strict=True, pattern=r"^[a-z][a-z0-9_]{0,59}$")]
KINDS = ("PRODUCT", "PO", "SO", "RECEIPT", "OPENING", "ISSUE", "INTERNAL_MOVE", "TRANSFER",
         "ADJUSTMENT", "CUSTOMER_RETURN", "SUPPLIER_RETURN", "REVERSAL")
RESERVED = {"quantity", "basequantity", "quantitybase", "uom", "baseuom", "baseuomid", "uomid",
            "owner", "ownerid", "warehouse", "warehouseid", "destinationwarehouseid", "price",
            "referenceunitprice", "unitprice", "priceread", "pricewrite", "permission", "permissions",
            "ledger", "stockmove", "stockbalance", "onhand", "reserved", "available", "receiptplan",
            "attributes", "version", "status", "id", "productid", "consignmentid", "factorsnapshot",
            "executionkey", "approval", "createdby", "businessdate", "role", "roles"}


def safe_code(code):
    if re.sub(r"[^a-z0-9]", "", code.removeprefix("cf_")) in RESERVED:
        raise ValueError("Reserved core field")
    return code


class FieldRules(Contract):
    max_length: int = Field(default=2000, ge=1, le=2000, strict=True)
    minimum: str | None = Field(default=None, pattern=r"^-?(?:0|[1-9][0-9]{0,13})(?:\.[0-9]{1,6})?$")
    maximum: str | None = Field(default=None, pattern=r"^-?(?:0|[1-9][0-9]{0,13})(?:\.[0-9]{1,6})?$")
    choices: list[Annotated[str, Field(strict=True, min_length=1, max_length=100)]] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def valid(self):
        if len(set(self.choices)) != len(self.choices):
            raise ValueError("Duplicate choices")
        if self.minimum is not None and self.maximum is not None and Decimal(self.minimum) > Decimal(self.maximum):
            raise ValueError("Invalid bounds")
        return self


class FieldDefinition(Contract):
    code: Code
    label: str = Field(min_length=1, max_length=120, strict=True)
    value_type: Literal["TEXT", "INTEGER", "DECIMAL", "BOOLEAN", "DATE", "ENUM"]
    required: StrictBool = False
    visibility: Literal["BUSINESS", "PRICE"] = "BUSINESS"
    validation: FieldRules = Field(default_factory=FieldRules)

    _code = field_validator("code")(safe_code)

    @model_validator(mode="after")
    def rules_match_type(self):
        if bool(self.validation.choices) != (self.value_type == "ENUM"):
            raise ValueError("Choices only for enum and required for enum")
        if self.value_type not in {"INTEGER", "DECIMAL"} and (self.validation.minimum is not None or self.validation.maximum is not None):
            raise ValueError("Numeric bounds only for numbers")
        if self.value_type != "TEXT" and self.validation.max_length != 2000:
            raise ValueError("Text length only for text")
        return self


class SchemaWrite(Contract):
    expected_version: int = Field(ge=0, strict=True)
    reason: Reason
    fields: list[FieldDefinition] = Field(max_length=50)

    @field_validator("fields")
    @classmethod
    def distinct(cls, fields):
        if len({f.code for f in fields}) != len(fields):
            raise ValueError("Duplicate field codes")
        return fields


class SchemaView(Contract):
    entity_type: EntityType
    revision_id: UUID | None
    version: int = Field(ge=0)
    fields: list[FieldDefinition]


class ValuesWrite(Contract):
    expected_version: int = Field(ge=1, strict=True)
    expected_revision_id: UUID | None
    revision_id: UUID
    reason: Reason
    values: dict[Code, Value] = Field(max_length=50)

    @field_validator("values")
    @classmethod
    def flat(cls, values):
        for code, value in values.items():
            safe_code(code)
            if isinstance(value, str) and len(value) > 2000:
                raise ValueError("Value too long")
            if type(value) is int and abs(value) > 99999999999999:
                raise ValueError("Integer too large")
        return values


class CustomResult(Contract):
    id: UUID
    version: int = Field(ge=1)
    revision_id: UUID
    request_id: UUID


class ValuesView(Contract):
    target_type: TargetType
    id: UUID
    version: int
    warehouse_id: UUID | None
    revision_id: UUID | None
    schema_snapshot: SchemaView = Field(alias="schema")
    values: dict[str, Value]
    editable: bool
    can_write_price: bool


class HistoryEntry(Contract):
    target_version: int
    revision_id: UUID
    schema_snapshot: SchemaView = Field(alias="schema")
    values: dict[str, Value]


class HistoryPage(Contract):
    items: list[HistoryEntry]
    next_before: int | None


def validate_value(field: FieldDefinition, value):
    """Raise without interpolating potentially restricted values into errors."""
    if value is None:
        if field.required:
            raise ValueError("Required")
        return
    if field.required and isinstance(value, str) and not value.strip():
        raise ValueError("Required")
    kind, rules = field.value_type, field.validation
    valid = ((kind == "TEXT" and type(value) is str and len(value) <= rules.max_length)
             or (kind == "INTEGER" and type(value) is int and abs(value) <= 99999999999999)
             or (kind == "BOOLEAN" and type(value) is bool)
             or (kind == "ENUM" and type(value) is str and value in rules.choices))
    if kind == "DECIMAL":
        valid = type(value) is str and bool(re.fullmatch(r"-?(?:0|[1-9][0-9]{0,13})(?:\.[0-9]{1,6})?", value))
    if kind == "DATE":
        valid = type(value) is str and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value))
        if valid:
            date.fromisoformat(value)
    if not valid:
        raise ValueError("Invalid type or constraint")
    if kind in {"INTEGER", "DECIMAL"}:
        number = Decimal(value)
        if (rules.minimum is not None and number < Decimal(rules.minimum)) or (rules.maximum is not None and number > Decimal(rules.maximum)):
            raise ValueError("Out of range")
