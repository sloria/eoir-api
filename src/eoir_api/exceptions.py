class EOIRAPIError(Exception):
    """Base class for all application errors."""


class ConfigurationError(EOIRAPIError):
    """Raised when settings are missing or invalid."""


class QueueTimeoutError(EOIRAPIError):
    """Raised when a request would wait too long or its tenant is at its cap."""

    def __init__(self, message: str, *, max_concurrency: int | None = None) -> None:
        super().__init__(message)
        self.max_concurrency = max_concurrency


class BrowserUnavailableError(EOIRAPIError):
    """Raised when every browser is in a captcha cooldown."""

    def __init__(self, message: str, *, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class QuotaExceededError(EOIRAPIError):
    """Raised when a tenant has used up its lookup quota."""

    def __init__(self, message: str, *, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after
