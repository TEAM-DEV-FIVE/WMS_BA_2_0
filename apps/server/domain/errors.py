"""Domain errors have no dependency on HTTP, persistence, or UI."""


class DomainError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.field = field


def require_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise DomainError("STALE_VERSION", "Dữ liệu đã thay đổi. Hãy tải lại trước khi tiếp tục.")
