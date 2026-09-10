from __future__ import annotations

from dataclasses import replace

from susanoox.config.credentials import SecureCredentialStore
from susanoox.config.paths import AppPaths
from susanoox.config.settings import Settings
from susanoox.sessions.storage import SessionStore
from susanoox.ui.app import SusanooxApp
from susanoox.utils.errors import SessionError


def run_application(
    settings: Settings,
    *,
    resume_session_id: str | None = None,
    resume_uses_saved_model: bool = True,
) -> None:
    paths = AppPaths.discover()
    session_store = SessionStore(paths.data_dir / "sessions.sqlite3")
    session_store.initialize()
    if resume_session_id is None:
        session = session_store.create(project_root=settings.project_path, model=settings.model)
    else:
        session = session_store.get(resume_session_id)
        if session is None:
            matches = [
                item for item in session_store.list() if item.id.startswith(resume_session_id)
            ]
            if len(matches) != 1:
                raise SessionError(f"Session {resume_session_id!r} was not found or is ambiguous.")
            session = matches[0]
        if session.project_root != str(settings.project_path.resolve()):
            raise SessionError("That session belongs to a different project root.")
        if resume_uses_saved_model:
            settings = replace(settings, model=session.model)
    app = SusanooxApp(
        settings=settings,
        credential_store=SecureCredentialStore(),
        session_store=session_store,
        session_id=session.id,
    )
    app.run()
