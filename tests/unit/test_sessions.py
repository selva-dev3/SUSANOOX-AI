from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from susanoox.agent.planner import PlanService
from susanoox.agent.retry import RetryPolicy
from susanoox.agent.types import AttemptRecord
from susanoox.context.models import ContextFile, ContextSnapshot
from susanoox.models.protocol import ConversationMessage, TokenUsage
from susanoox.sessions.storage import SessionStore
from susanoox.summarization.service import ConversationSummarizer
from susanoox.utils.errors import SessionError


def test_session_round_trip_and_resume_data(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "data" / "sessions.sqlite3")
    store.initialize()
    session = store.create(project_root=tmp_path, model="susanoox-fast")
    messages = (
        ConversationMessage(role="system", content="system"),
        ConversationMessage(role="user", content="Fix auth"),
        ConversationMessage(role="assistant", content="Done"),
    )
    store.save_messages(session.id, messages)
    summary = ConversationSummarizer(trigger_chars=1, recent_messages=1).compact(messages)
    store.save_summary(session.id, summary)
    plan = PlanService().create(session_id=session.id, objective="Fix auth")
    store.save_plan(plan)
    context = ContextSnapshot(
        query="Fix auth with sk-forge-abcdefgh",
        project_root=str(tmp_path),
        files=(
            ContextFile(path="src/auth.py", score=2, reasons=("path match",), excerpt="secret"),
        ),
        total_chars=6,
    )
    store.save_context_metadata(session.id, context)
    attempt = AttemptRecord(
        session_id=session.id,
        action="stream_chat",
        category="service_transient",
        attempt=1,
        max_attempts=2,
        fingerprint=RetryPolicy.fingerprint("stream_chat", "service_transient"),
    )
    store.add_attempt(attempt)
    store.save_usage(
        session.id,
        {"susanoox-fast": TokenUsage(prompt_tokens=10, completion_tokens=5)},
    )

    assert store.load_messages(session.id) == messages
    assert store.load_summary(session.id) == summary
    assert store.latest_plan(session.id) == plan
    restored_context = store.load_context_metadata(context.id)
    assert restored_context is not None
    assert restored_context.files[0].excerpt == ""
    assert restored_context.total_chars == 0
    assert "sk-forge" not in restored_context.query
    assert store.load_attempts(session.id) == (attempt,)
    assert store.load_usage(session.id)["susanoox-fast"].total_tokens == 15
    assert store.list(project_root=tmp_path)[0].id == session.id


def test_clear_summary_does_not_delete_raw_messages(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.sqlite3")
    store.initialize()
    session = store.create(project_root=tmp_path, model="susanoox-fast")
    messages = (
        ConversationMessage(role="system", content="system"),
        ConversationMessage(role="user", content="hello"),
    )
    store.save_messages(session.id, messages)
    summary = ConversationSummarizer(trigger_chars=1, recent_messages=1).compact(messages)
    store.save_summary(session.id, summary)

    store.clear_summary(session.id)

    assert store.load_summary(session.id) is None
    assert store.load_messages(session.id) == messages


def test_session_persistence_redacts_likely_credentials(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.sqlite3")
    store.initialize()
    session = store.create(project_root=tmp_path, model="susanoox-fast")
    store.save_messages(
        session.id,
        (
            ConversationMessage(role="system", content="system"),
            ConversationMessage(role="user", content="token sk-forge-abcdefghijk"),
        ),
    )

    restored = store.load_messages(session.id)

    assert "sk-forge" not in restored[-1].content
    assert "[REDACTED]" in restored[-1].content


def test_corrupted_session_is_reported_without_raw_database_error(tmp_path: Path) -> None:
    database = tmp_path / "sessions.sqlite3"
    store = SessionStore(database)
    store.initialize()
    session = store.create(project_root=tmp_path, model="susanoox-fast")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE sessions SET payload = ? WHERE id = ?", ("not-json", session.id))

    with pytest.raises(SessionError, match="metadata is invalid"):
        store.get(session.id)
