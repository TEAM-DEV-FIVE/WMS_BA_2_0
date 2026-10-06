from datetime import date
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import AfterValidator, Field, StringConstraints, create_model, model_validator

from packages.contracts import Contract

Code = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, to_upper=True,
                                       min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]


def positive(value: str) -> str:
    if Decimal(value) <= 0:
        raise ValueError("Factor must be positive")
    return value


Factor = Annotated[str, StringConstraints(strict=True, pattern=r"^(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,8})?$"), AfterValidator(positive)]
Amount = Annotated[str, StringConstraints(strict=True, pattern=r"^(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,4})?$")]


class UomData(Contract):
    code: Code = Field(max_length=30)
    name: Name = Field(max_length=80)
    decimal_places: int = Field(ge=0, le=6, strict=True)
    is_active: bool = Field(default=True, strict=True)


class CategoryData(Contract):
    code: Code = Field(max_length=40)
    name: Name = Field(max_length=160)
    parent_id: UUID | None = None
    is_active: bool = Field(default=True, strict=True)


class ProductData(Contract):
    sku: Code
    name: Name
    category_id: UUID | None = None
    base_uom_id: UUID
    tracking: Literal["NONE", "LOT", "SERIAL"]
    expiry_required: bool = Field(default=False, strict=True)
    is_active: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def expiry_for_lots(self):
        if self.expiry_required and self.tracking != "LOT":
            raise ValueError("Only LOT products can require expiry")
        return self


class PartnerData(Contract):
    code: Code = Field(max_length=60)
    name: Name
    is_customer: bool = Field(default=False, strict=True)
    is_supplier: bool = Field(default=False, strict=True)
    tax_code: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=2000)
    is_active: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def partner_kind(self):
        if not (self.is_customer or self.is_supplier):
            raise ValueError("Choose customer or supplier")
        return self


class WarehouseData(Contract):
    code: Code = Field(max_length=40)
    name: Name = Field(max_length=160)
    address: str | None = Field(default=None, max_length=2000)
    is_active: bool = Field(default=True, strict=True)


class LocationData(Contract):
    code: Code
    name: Name = Field(max_length=160)
    warehouse_id: UUID
    parent_id: UUID | None = None
    kind: Literal["GROUP", "STORAGE", "RECEIVING", "QUARANTINE", "SHIPPING"]
    is_active: bool = Field(default=True, strict=True)


class BarcodeData(Contract):
    code: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1,
                                         max_length=160, pattern=r"^[!-~]+$")]
    product_uom_id: UUID
    is_active: bool = Field(default=True, strict=True)


class ConversionCreate(Contract):
    product_id: UUID
    uom_id: UUID
    factor: Factor
    expected_product_version: int = Field(ge=1, strict=True)
    reason: Reason


class ConversionView(Contract):
    id: UUID
    product_id: UUID
    uom_id: UUID
    factor: str
    revision: int
    is_active: bool


class PriceCreate(Contract):
    effective_on: date
    amount: Amount
    currency: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z]{3}$")]
    source: Reason


class PriceView(PriceCreate):
    id: UUID
    product_id: UUID


T = TypeVar("T")


class Page(Contract, Generic[T]):
    items: list[T]
    next_after: UUID | None = None


def entity_models(data: type[Contract]):
    """Each route has concrete request/response schemas in generated OpenAPI."""
    name = data.__name__.removesuffix("Data")
    create = create_model(name + "Create", __base__=data, reason=(Reason, ...))
    update = create_model(name + "Update", __base__=create,
                          expected_version=(Annotated[int, Field(ge=1, strict=True)], ...))
    view = create_model(name + "View", __base__=data, id=(UUID, ...), version=(int, ...))
    return create, update, view
