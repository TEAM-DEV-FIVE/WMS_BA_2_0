"""Read-only projections for document review; prices and arbitrary attributes are excluded."""

from datetime import datetime
from uuid import UUID

from pydantic import JsonValue

from packages.contracts import Contract


class AssignmentCandidate(Contract):
    id: UUID
    username: str
    display_name: str


class AssignmentCandidatePage(Contract):
    items: list[AssignmentCandidate]
    next_after: UUID | None


class ApprovalSnapshot(Contract):
    id: UUID
    document_version: int
    status: str
    created_at: datetime
    content: dict[str, JsonValue] | None


class DocumentReview(Contract):
    document_id: UUID
    current_version: int
    current: dict[str, JsonValue]
    snapshots: list[ApprovalSnapshot]
