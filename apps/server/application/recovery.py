"""Per-request lookup flag propagates into FastAPI's synchronous worker context."""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class RecoveryContext:
    lookup_only: bool
    key: str | None = None
    result: dict | None = None
    rejected: bool = False


recovery_context: ContextVar[RecoveryContext | None] = ContextVar("wms_recovery", default=None)
