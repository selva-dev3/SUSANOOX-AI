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
