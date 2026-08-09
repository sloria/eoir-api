class EoirApiError(Exception):
    """Base class for all application errors."""


class ConfigurationError(EoirApiError):
    """Raised when settings are missing or invalid."""


class UnknownNationalityError(EoirApiError):
    """Raised when a nationality code or name can't be resolved."""


class InvalidANumberError(EoirApiError):
    """Raised when an A-Number isn't valid."""


class QueueTimeoutError(EoirApiError):
    """Raised when a request would wait too long behind the browser lock."""
