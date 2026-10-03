from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from packages.contracts import Contract
from packages.contracts.master_data import Reason

ImportKind = Literal[
    "01_uom",
    "02_categories",
    "03_warehouses",
    "04_locations",
    "05_products",
    "06_product_uom",
    "07_barcodes",
    "08_partners",
    "09_lots",
    "10_serials",
    "11_opening",
    "12_open_orders",
    "14_prices",
]


class FileView(Contract):
    id: UUID
    original_name: str
    sha256: str
    size_bytes: int
    kind: ImportKind
    warehouse_id: UUID | None
    ready: bool


class ImportCreate(Contract):
    file_id: UUID
    reason: Reason
    signed_count_reference: Reason | None = None


class ImportAction(Contract):
    expected_version: int = Field(ge=1, strict=True)
    reason: Reason


class ImportCommit(ImportAction):
    commit_token: UUID
    file_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ImportError(Contract):
    row_no: int
    column: str
    code: str
    message: str
    suggested_fix: str = "Sửa dữ liệu nguồn rồi tải lại và chạy dry-run."


class ImportView(Contract):
    id: UUID
    kind: str
    file_id: UUID
    warehouse_id: UUID | None
    status: str
    version: int
    generation: int
    file_hash: str
    mapping_version: str
    total_rows: int
    processed_rows: int
    errors: list[ImportError]
    commit_token: UUID | None
    token_expires_at: datetime | None
    result: dict | None


class ImportRowView(Contract):
    row_no: int
    payload: dict
    errors: list[ImportError]
    target_id: UUID | None
    status: str


class ImportRows(Contract):
    items: list[ImportRowView]
    next_after: int | None


class ImportAck(Contract):
    id: UUID
    status: str
    version: int
    request_id: UUID
    targets: list[dict] = []
