"""Metadata only; reading history never grants file access or replays a command."""

from datetime import datetime
from uuid import UUID

from packages.contracts import Contract


class JobHistoryItem(Contract):
    id: UUID
    kind: str
    status: str
    created_at: datetime
    error_code: str | None = None
    expired: bool = False


class JobHistoryPage(Contract):
    items: list[JobHistoryItem]
    next_after: UUID | None
