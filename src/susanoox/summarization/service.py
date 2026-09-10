from __future__ import annotations

import re
from collections.abc import Sequence

from susanoox.models.protocol import ConversationMessage
from susanoox.security.redaction import redact_secrets
from susanoox.summarization.models import ConversationSummary

_PATH = re.compile(r"(?<![\w./-])(?:[\w.-]+/)+[\w.-]+")
_ERROR_WORDS = ("error", "failed", "failure", "exception", "timeout")
_DECISION_WORDS = ("decided", "selected", "use ", "must ", "do not ")


class ConversationSummarizer:
    """Creates a deterministic fact ledger; raw messages remain the source of truth."""

    def __init__(
        self,
        *,
        trigger_chars: int = 48_000,
        recent_messages: int = 8,
        max_summary_chars: int | None = None,
    ) -> None:
        self.trigger_chars = trigger_chars
        self.recent_messages = recent_messages
        self.max_summary_chars = max_summary_chars or max(1_000, min(12_000, trigger_chars // 2))

    def needs_compaction(
        self,
        messages: Sequence[ConversationMessage],
        summary: ConversationSummary | None,
    ) -> bool:
        covered = summary.covered_message_count if summary else 1
        eligible = messages[covered : max(covered, len(messages) - self.recent_messages)]
        return sum(len(message.content) for message in eligible) >= self.trigger_chars

    def compact(
        self,
        messages: Sequence[ConversationMessage],
        previous: ConversationSummary | None = None,
        *,
        recent_messages: int | None = None,
    ) -> ConversationSummary:
        keep_from = max(1, len(messages) - (recent_messages or self.recent_messages))
        newly_covered = messages[previous.covered_message_count if previous else 1 : keep_from]
        requirements = list(previous.user_requirements if previous else ())
        decisions = list(previous.decisions if previous else ())
        referenced_files = list(previous.referenced_files if previous else ())
        changed_files = list(previous.changed_files if previous else ())
        unresolved = list(previous.unresolved_items if previous else ())
        errors = list(previous.errors if previous else ())
        narrative_parts = [previous.narrative] if previous and previous.narrative else []

        for message in newly_covered:
            clean = redact_secrets(" ".join(message.content.split()))
            if not clean:
                continue
            shortened = clean[:700]
            narrative_parts.append(f"{message.role}: {shortened}")
            lowered = clean.casefold()
            if message.role == "user":
                self._append_unique(requirements, shortened, limit=24)
                if clean.endswith("?") or "remaining" in lowered:
                    self._append_unique(unresolved, shortened, limit=16)
            if message.role == "user" and any(word in lowered for word in _DECISION_WORDS):
                self._append_unique(decisions, shortened, limit=20)
            if any(word in lowered for word in _ERROR_WORDS):
                self._append_unique(errors, shortened, limit=12)
            for path in _PATH.findall(clean):
                self._append_unique(referenced_files, path, limit=40)

        narrative = "\n".join(narrative_parts)
        if len(narrative) > 10_000:
            narrative = narrative[-10_000:]
        return ConversationSummary(
            version=(previous.version + 1) if previous else 1,
            covered_message_count=keep_from,
            narrative=narrative,
            user_requirements=tuple(requirements),
            decisions=tuple(decisions),
            referenced_files=tuple(referenced_files),
            changed_files=tuple(changed_files),
            unresolved_items=tuple(unresolved),
            errors=tuple(errors),
        )

    def reconstruct(
        self,
        messages: Sequence[ConversationMessage],
        summary: ConversationSummary | None,
    ) -> list[ConversationMessage]:
        if summary is None:
            return list(messages)
        system = messages[0]
        recent_start = max(summary.covered_message_count, len(messages) - self.recent_messages)
        return [
            system,
            ConversationMessage(
                role="system",
                content=summary.as_system_message(max_chars=self.max_summary_chars),
            ),
            *messages[recent_start:],
        ]

    @staticmethod
    def _append_unique(values: list[str], value: str, *, limit: int) -> None:
        if value not in values:
            values.append(value)
        if len(values) > limit:
            del values[: len(values) - limit]
