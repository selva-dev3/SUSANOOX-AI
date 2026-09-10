from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from susanoox.agent.types import AttemptRecord, ExecutionPlan, utc_now
from susanoox.config.settings import CHAT_MODELS, ModelName
from susanoox.context.models import ContextFile, ContextSnapshot
from susanoox.models.protocol import ConversationMessage, TokenUsage
from susanoox.security.redaction import redact_secrets
from susanoox.sessions.schema import SessionRecord, StoredMessage
from susanoox.summarization.models import ConversationSummary
from susanoox.utils.errors import SessionError

_SCHEMA_VERSION = 1


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS messages (
                        session_id TEXT NOT NULL,
                        sequence INTEGER NOT NULL,
                        payload TEXT NOT NULL,
                        PRIMARY KEY (session_id, sequence),
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS summaries (
                        session_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS plans (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        payload TEXT NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS plans_session ON plans(session_id, version DESC);
                    CREATE TABLE IF NOT EXISTS attempts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS attempts_session ON attempts(session_id, id);
                    CREATE TABLE IF NOT EXISTS usage (
                        session_id TEXT NOT NULL,
                        model TEXT NOT NULL,
                        prompt_tokens INTEGER NOT NULL,
                        completion_tokens INTEGER NOT NULL,
                        PRIMARY KEY (session_id, model),
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS contexts (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    );
                    """
                )
                version = connection.execute(
                    "SELECT value FROM metadata WHERE key = 'schema_version'"
                ).fetchone()
                if version is None:
                    connection.execute(
                        "INSERT INTO metadata(key, value) VALUES ('schema_version', ?)",
                        (str(_SCHEMA_VERSION),),
                    )
                elif int(version[0]) > _SCHEMA_VERSION:
                    raise SessionError("Session data was created by a newer Susanoox version.")
            if os.name != "nt":
                self.path.parent.chmod(0o700)
                self.path.chmod(0o600)
        except (OSError, sqlite3.Error, ValueError) as error:
            raise SessionError("Unable to initialize local session storage.") from error

    def create(
        self, *, project_root: Path, model: ModelName, title: str = "New session"
    ) -> SessionRecord:
        session = SessionRecord(title=title, project_root=str(project_root), model=model)
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO sessions(id, payload) VALUES (?, ?)",
                    (session.id, session.model_dump_json()),
                )
        except sqlite3.Error as error:
            raise SessionError("Unable to create the session.") from error
        return session

    def get(self, session_id: str) -> SessionRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
        except sqlite3.Error as error:
            raise SessionError("Unable to read the session.") from error
        return self._parse_session(row[0]) if row else None

    def list(
        self, *, project_root: Path | None = None, limit: int = 20
    ) -> tuple[SessionRecord, ...]:
        try:
            with self._connect() as connection:
                rows = connection.execute("SELECT payload FROM sessions").fetchall()
        except sqlite3.Error as error:
            raise SessionError("Unable to list sessions.") from error
        sessions = [self._parse_session(row[0]) for row in rows]
        if project_root is not None:
            expected = str(project_root.resolve())
            sessions = [session for session in sessions if session.project_root == expected]
        sessions.sort(key=lambda session: session.updated_at, reverse=True)
        return tuple(session for session in sessions if not session.archived)[:limit]

    def save_messages(self, session_id: str, messages: Sequence[ConversationMessage]) -> None:
        now = utc_now()
        stored = [
            StoredMessage(
                sequence=index,
                role=message.role,
                content=redact_secrets(message.content),
                had_images=bool(message.images),
            )
            for index, message in enumerate(messages)
        ]
        try:
            with self._connect() as connection:
                connection.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                connection.executemany(
                    "INSERT INTO messages(session_id, sequence, payload) VALUES (?, ?, ?)",
                    [(session_id, item.sequence, item.model_dump_json()) for item in stored],
                )
                row = connection.execute(
                    "SELECT payload FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
                if row:
                    session = self._parse_session(row[0]).model_copy(update={"updated_at": now})
                    connection.execute(
                        "UPDATE sessions SET payload = ? WHERE id = ?",
                        (session.model_dump_json(), session_id),
                    )
        except sqlite3.Error as error:
            raise SessionError("Unable to save conversation messages.") from error

    def rename(self, session_id: str, title: str) -> None:
        normalized = redact_secrets(" ".join(title.split()))[:160]
        if not normalized:
            raise SessionError("Session title cannot be empty.")
        session = self.get(session_id)
        if session is None:
            raise SessionError("The session no longer exists.")
        updated = session.model_copy(update={"title": normalized, "updated_at": utc_now()})
        try:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE sessions SET payload = ? WHERE id = ?",
                    (updated.model_dump_json(), session_id),
                )
        except sqlite3.Error as error:
            raise SessionError("Unable to rename the session.") from error

    def load_messages(self, session_id: str) -> tuple[ConversationMessage, ...]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT payload FROM messages WHERE session_id = ? ORDER BY sequence",
                    (session_id,),
                ).fetchall()
            stored = tuple(StoredMessage.model_validate_json(row[0]) for row in rows)
            if any(item.sequence != index for index, item in enumerate(stored)):
                raise SessionError("Stored conversation message order is invalid.")
            if stored and stored[0].role != "system":
                raise SessionError("Stored conversation is missing its system boundary.")
            return tuple(item.conversation_message() for item in stored)
        except (sqlite3.Error, ValidationError) as error:
            raise SessionError("Stored conversation messages are invalid or unreadable.") from error

    def save_summary(self, session_id: str, summary: ConversationSummary) -> None:
        safe_summary = summary.model_copy(
            update={
                "narrative": redact_secrets(summary.narrative),
                "user_requirements": tuple(
                    redact_secrets(value) for value in summary.user_requirements
                ),
                "decisions": tuple(redact_secrets(value) for value in summary.decisions),
                "referenced_files": tuple(
                    redact_secrets(value) for value in summary.referenced_files
                ),
                "changed_files": tuple(redact_secrets(value) for value in summary.changed_files),
                "unresolved_items": tuple(
                    redact_secrets(value) for value in summary.unresolved_items
                ),
                "errors": tuple(redact_secrets(value) for value in summary.errors),
            }
        )
        self._upsert_json("summaries", "session_id", session_id, safe_summary.model_dump_json())

    def clear_summary(self, session_id: str) -> None:
        try:
            with self._connect() as connection:
                connection.execute("DELETE FROM summaries WHERE session_id = ?", (session_id,))
        except sqlite3.Error as error:
            raise SessionError("Unable to clear the conversation summary.") from error

    def load_summary(self, session_id: str) -> ConversationSummary | None:
        payload = self._select_payload("summaries", "session_id", session_id)
        if payload is None:
            return None
        try:
            return ConversationSummary.model_validate_json(payload)
        except ValidationError as error:
            raise SessionError("Stored conversation summary is invalid.") from error

    def save_plan(self, plan: ExecutionPlan) -> None:
        safe_plan = plan.model_copy(
            update={
                "objective": redact_secrets(plan.objective),
                "assumptions": tuple(redact_secrets(value) for value in plan.assumptions),
                "risks": tuple(redact_secrets(value) for value in plan.risks),
                "validation_strategy": tuple(
                    redact_secrets(value) for value in plan.validation_strategy
                ),
                "steps": tuple(
                    step.model_copy(
                        update={
                            "title": redact_secrets(step.title),
                            "expected_result": redact_secrets(step.expected_result),
                        }
                    )
                    for step in plan.steps
                ),
            }
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO plans"
                    "(id, session_id, version, payload) VALUES (?, ?, ?, ?)",
                    (
                        safe_plan.id,
                        safe_plan.session_id,
                        safe_plan.version,
                        safe_plan.model_dump_json(),
                    ),
                )
        except sqlite3.Error as error:
            raise SessionError("Unable to save the execution plan.") from error

    def save_context_metadata(self, session_id: str, snapshot: ContextSnapshot) -> None:
        metadata = snapshot.model_copy(
            update={
                "query": redact_secrets(snapshot.query),
                "files": tuple(
                    ContextFile(
                        path=redact_secrets(item.path),
                        score=item.score,
                        reasons=tuple(redact_secrets(reason) for reason in item.reasons),
                        excerpt="",
                        truncated=item.truncated,
                    )
                    for item in snapshot.files
                ),
                "total_chars": 0,
            }
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO contexts(id, session_id, payload) VALUES (?, ?, ?)",
                    (metadata.id, session_id, metadata.model_dump_json()),
                )
        except sqlite3.Error as error:
            raise SessionError("Unable to save context-selection metadata.") from error

    def load_context_metadata(self, context_id: str) -> ContextSnapshot | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM contexts WHERE id = ?", (context_id,)
                ).fetchone()
            return ContextSnapshot.model_validate_json(row[0]) if row else None
        except (sqlite3.Error, ValidationError) as error:
            raise SessionError("Stored context-selection metadata is invalid.") from error

    def latest_plan(self, session_id: str) -> ExecutionPlan | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM plans WHERE session_id = ? ORDER BY version DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
            return ExecutionPlan.model_validate_json(row[0]) if row else None
        except (sqlite3.Error, ValidationError) as error:
            raise SessionError("Stored execution plan is invalid or unreadable.") from error

    def add_attempt(self, attempt: AttemptRecord) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO attempts(session_id, payload) VALUES (?, ?)",
                    (attempt.session_id, attempt.model_dump_json()),
                )
        except sqlite3.Error as error:
            raise SessionError("Unable to record retry history.") from error

    def load_attempts(self, session_id: str) -> tuple[AttemptRecord, ...]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT payload FROM attempts WHERE session_id = ? ORDER BY id",
                    (session_id,),
                ).fetchall()
            return tuple(AttemptRecord.model_validate_json(row[0]) for row in rows)
        except (sqlite3.Error, ValidationError) as error:
            raise SessionError("Stored retry history is invalid or unreadable.") from error

    def save_usage(self, session_id: str, usage_by_model: dict[ModelName, TokenUsage]) -> None:
        try:
            with self._connect() as connection:
                connection.executemany(
                    """INSERT OR REPLACE INTO usage
                    (session_id, model, prompt_tokens, completion_tokens) VALUES (?, ?, ?, ?)""",
                    [
                        (
                            session_id,
                            model,
                            usage.prompt_tokens,
                            usage.completion_tokens,
                        )
                        for model, usage in usage_by_model.items()
                    ],
                )
        except sqlite3.Error as error:
            raise SessionError("Unable to save token usage.") from error

    def load_usage(self, session_id: str) -> dict[ModelName, TokenUsage]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT model, prompt_tokens, completion_tokens "
                    "FROM usage WHERE session_id = ?",
                    (session_id,),
                ).fetchall()
        except sqlite3.Error as error:
            raise SessionError("Unable to load token usage.") from error
        result: dict[ModelName, TokenUsage] = {}
        for model, prompt_tokens, completion_tokens in rows:
            if model not in CHAT_MODELS:
                continue
            result[model] = TokenUsage(
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(completion_tokens),
            )
        return result

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _select_payload(self, table: str, key: str, value: str) -> str | None:
        if table not in {"summaries"} or key != "session_id":
            raise ValueError("Unsupported storage query")
        try:
            with self._connect() as connection:
                row = connection.execute(
                    f"SELECT payload FROM {table} WHERE {key} = ?",  # noqa: S608
                    (value,),
                ).fetchone()
        except sqlite3.Error as error:
            raise SessionError("Unable to read session data.") from error
        return str(row[0]) if row else None

    def _upsert_json(self, table: str, key: str, value: str, payload: str) -> None:
        if table not in {"summaries"} or key != "session_id":
            raise ValueError("Unsupported storage update")
        try:
            with self._connect() as connection:
                connection.execute(
                    f"INSERT OR REPLACE INTO {table}({key}, payload) VALUES (?, ?)",  # noqa: S608
                    (value, payload),
                )
        except sqlite3.Error as error:
            raise SessionError("Unable to save session data.") from error

    @staticmethod
    def _parse_session(payload: str) -> SessionRecord:
        try:
            return SessionRecord.model_validate_json(payload)
        except ValidationError as error:
            raise SessionError("Stored session metadata is invalid.") from error
