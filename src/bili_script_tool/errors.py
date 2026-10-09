"""Application-specific exceptions shown cleanly in the desktop UI."""


class ApplicationError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(ApplicationError):
    """Raised when required settings are missing or invalid."""


class DependencyError(ApplicationError):
    """Raised when an external command or Python dependency is unavailable."""


class DataValidationError(ApplicationError):
    """Raised when a case-library record is malformed."""


class ExternalCommandError(ApplicationError):
    """Raised when a media command exits unsuccessfully."""


class AIServiceError(ApplicationError):
    """Raised when the language-model request or response is invalid."""

