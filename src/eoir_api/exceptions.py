class EoirApiError(Exception):
    """Base class for all application errors."""


class ConfigurationError(EoirApiError):
    """Raised when settings are missing or invalid."""


class QueueTimeoutError(EoirApiError):
    """Raised when a request would wait too long behind the browser lock."""
