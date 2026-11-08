class EoirApiError(Exception):
    """Base class for all application errors."""


class ConfigurationError(EoirApiError):
    """Raised when settings are missing or invalid."""


class QueueTimeoutError(EoirApiError):
    """Raised when a request would wait too long or its tenant is at its cap."""

    def __init__(self, message: str, *, max_concurrency: int | None = None) -> None:
        super().__init__(message)
        self.max_concurrency = max_concurrency


class BrowserUnavailableError(EoirApiError):
    """Raised when every browser is in a captcha cooldown."""

    def __init__(self, message: str, *, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class QuotaExceededError(EoirApiError):
    """Raised when a tenant has used up its lookup quota."""

    def __init__(self, message: str, *, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after
