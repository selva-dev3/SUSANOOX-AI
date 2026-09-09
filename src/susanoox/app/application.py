from __future__ import annotations

from susanoox.config.credentials import SecureCredentialStore
from susanoox.config.settings import Settings
from susanoox.ui.app import SusanooxApp


def run_application(settings: Settings) -> None:
    app = SusanooxApp(settings=settings, credential_store=SecureCredentialStore())
    app.run()
