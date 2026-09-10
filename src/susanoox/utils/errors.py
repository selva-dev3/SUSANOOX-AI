"""Application errors safe to present in the terminal UI."""


class SusanooxError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(SusanooxError):
    """Configuration could not be loaded or validated."""


class CredentialError(SusanooxError):
    """Credential storage or retrieval failed."""


class AuthenticationError(SusanooxError):
    """The API rejected the configured credentials."""


class ServiceConnectionError(SusanooxError):
    """The Susanoox service could not be reached."""


class ServiceResponseError(SusanooxError):
    """The Susanoox service returned an unusable response."""


class AttachmentError(SusanooxError):
    """An image attachment could not be read or validated safely."""


class PlanError(SusanooxError):
    """A visible execution plan could not be created or validated."""


class ContextError(SusanooxError):
    """Project context could not be selected safely."""


class SessionError(SusanooxError):
    """Persistent session state could not be read or written."""


class RetryableServiceError(ServiceConnectionError):
    """A transient provider failure may be retried within policy."""


class ContextOverflowError(ServiceResponseError):
    """The assembled request exceeded the provider context window."""


class ModelOutputError(ServiceResponseError):
    """The model completed without a usable public response."""
