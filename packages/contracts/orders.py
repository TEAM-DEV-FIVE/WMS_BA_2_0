from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from packages.contracts import Contract, PositiveQuantity
from packages.contracts.master_data import Reason

OrderKind = Literal["PO", "SO", "RECEIPT", "OPENING", "ISSUE", "INTERNAL_MOVE"]
OrderStatus = Literal["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "PARTIAL", "COMPLETED", "CANCELLED"]


class OrderLineInput(Contract):
    product_id: UUID
    product_uom_id: UUID
    quantity: PositiveQuantity
    owner_id: UUID
    consignment_id: UUID | None = None


class OrderInput(Contract):
    warehouse_id: UUID
    partner_id: UUID
    business_date: date
    lines: list[OrderLineInput] = Field(min_length=1, max_length=200)
    reason: Reason


class OrderUpdate(OrderInput):
    expected_version: int = Field(ge=1, strict=True)


class OrderAction(Contract):
    expected_version: int = Field(ge=1, strict=True)
    reason: Reason


class AssignmentInput(OrderAction):
    user_ids: list[UUID] = Field(max_length=50)

    @model_validator(mode="after")
    def unique_users(self):
        if len(self.user_ids) != len(set(self.user_ids)):
            raise ValueError("Duplicate assignment")
        return self


class DecisionInput(OrderAction):
    decision: Literal["APPROVE", "REJECT"]


class OrderResult(Contract):
    id: UUID
    number: str
    kind: OrderKind
    warehouse_id: UUID
    status: OrderStatus
    version: int
    request_id: UUID
    approval_request_id: UUID | None = None


class OrderLineView(Contract):
    id: UUID
    line_no: int
    product_id: UUID
    sku: str
    product_name: str
    tracking: str
    base_uom_code: str
    uom_id: UUID
    product_uom_id: UUID | None
    uom_code: str
    quantity: str
    factor_snapshot: str
    base_quantity: str
    owner_id: UUID
    owner_code: str
    consignment_id: UUID | None
    posted_base: str
    closed_base: str
    remaining_base: str


class OrderSummary(Contract):
    id: UUID
    number: str
    kind: OrderKind
    status: OrderStatus
    warehouse_id: UUID
    partner_id: UUID | None
    partner_name: str | None
    business_date: date
    created_by: UUID
    creator_name: str
    created_at: datetime
    version: int


class ApprovalStepView(Contract):
    step_no: int
    roles: list[str]
    status: str
    decided_by: UUID | None
    decider_name: str | None
    decided_at: datetime | None
    comment: str | None


class ApprovalView(Contract):
    id: UUID
    document_id: UUID
    document_version: int
    current_version: int
    policy_revision: int
    requested_by: UUID
    status: str
    created_at: datetime
    steps: list[ApprovalStepView]
    can_decide: bool


class OrderView(OrderSummary):
    reason: str | None
    lines: list[OrderLineView]
    assigned_user_ids: list[UUID]
    approvals: list[ApprovalView]
    allowed_actions: list[str]


class OrderPage(Contract):
    items: list[OrderSummary]
    next_after: UUID | None
