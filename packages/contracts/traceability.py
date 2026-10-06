from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from packages.contracts import Contract
from packages.contracts.master_data import Code, Name, Reason

COMPANY_OWNER = UUID('00000000-0000-4000-8000-000000000001')
UNCLASSIFIED_OWNER = UUID('00000000-0000-4000-8000-000000000002')


class OwnerData(Contract):
    code: Code
    name: Name
    kind: Literal['COMPANY', 'CONSIGNOR', 'UNCLASSIFIED'] = 'CONSIGNOR'
    partner_id: UUID | None = None
    is_active: bool = Field(default=True, strict=True)


class AgreementData(Contract):
    code: Code
    owner_id: UUID
    warehouse_id: UUID
    valid_from: date
    valid_until: date
    source_ref: Reason
    is_active: bool = Field(default=True, strict=True)

    @model_validator(mode='after')
    def ordered_dates(self):
        if self.valid_until < self.valid_from:
            raise ValueError('Agreement ends before it starts')
        return self


class ConsignedQuantity(Contract):
    owner_id: UUID
    owner_partner_id: UUID
    quantity_base: str


class OwnershipBalance(Contract):
    warehouse_id: UUID
    location_id: UUID
    stock_item_id: UUID
    physical_base: str
    owned_base: str
    unclassified_base: str
    consigned_by_owner: list[ConsignedQuantity]
    as_of: datetime


class WarrantyInput(Contract):
    expected_version: int = Field(ge=0, strict=True)
    receipt_move_id: UUID
    starts_on: date | None = None
    ends_on: date | None = None
    evidence_ref: Reason | None = None
    reason: Reason

    @model_validator(mode='after')
    def ordered_dates(self):
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError('Warranty ends before it starts')
        return self


class SerialWarranty(Contract):
    serial_id: UUID
    product_id: UUID
    sku: str
    serial_code: str
    warehouse_id: UUID
    receipt_id: UUID | None
    receipt_number: str | None
    receipt_move_id: UUID | None
    supplier_partner_id: UUID | None
    supplier_code: str | None
    supplier_name: str | None
    received_on: date | None
    warranty_start_on: date | None
    warranty_ends_on: date | None
    warranty_evidence_ref: str | None
    status: Literal['VALID', 'EXPIRED', 'UNKNOWN']
    as_of: date
    version: int
    evidence_record_id: UUID | None


class SerialSearchItem(Contract):
    id: UUID
    product_id: UUID
    sku: str
    code: str


class WarrantyResult(Contract):
    id: UUID
    serial_id: UUID
    status: Literal['RECORDED'] = 'RECORDED'
    version: int
