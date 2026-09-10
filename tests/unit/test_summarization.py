from __future__ import annotations

from susanoox.models.protocol import ConversationMessage
from susanoox.summarization.service import ConversationSummarizer


def _messages() -> list[ConversationMessage]:
    return [
        ConversationMessage(role="system", content="system"),
        ConversationMessage(
            role="user", content="Fix src/auth.py; we must preserve compatibility."
        ),
        ConversationMessage(role="assistant", content="We will use validation and add tests."),
        ConversationMessage(role="user", content="The login test failed with a timeout."),
        ConversationMessage(role="assistant", content="Current response"),
    ]


def test_summary_preserves_requirements_files_and_errors() -> None:
    summarizer = ConversationSummarizer(trigger_chars=10, recent_messages=2)

    summary = summarizer.compact(_messages())

    assert summary.covered_message_count == 3
    assert any("src/auth.py" in path for path in summary.referenced_files)
    assert summary.user_requirements
    assert summary.decisions


def test_reconstruction_uses_summary_and_recent_messages_without_deleting_raw_history() -> None:
    messages = _messages()
    summarizer = ConversationSummarizer(trigger_chars=10, recent_messages=2)
    summary = summarizer.compact(messages)

    reconstructed = summarizer.reconstruct(messages, summary)

    assert len(messages) == 5
    assert reconstructed[0].role == "system"
    assert reconstructed[1].role == "system"
    assert "Conversation summary" in reconstructed[1].content
    assert reconstructed[-2:] == messages[-2:]


def test_adversarial_summary_is_bounded_below_compaction_trigger() -> None:
    messages = [ConversationMessage(role="system", content="system")]
    for index in range(80):
        role = "user" if index % 2 == 0 else "assistant"
        messages.append(
            ConversationMessage(
                role=role,
                content=(
                    f"Requirement {index}: must use src/module_{index}.py; "
                    "the previous operation failed with an exception. " + "x" * 650
                ),
            )
        )
    summarizer = ConversationSummarizer(trigger_chars=8_000, recent_messages=4)

    summary = summarizer.compact(messages)
    reconstructed = summarizer.reconstruct(messages, summary)

    summary_message = reconstructed[1].content
    assert len(summary_message) <= summarizer.max_summary_chars
    assert len(summary_message) < summarizer.trigger_chars
    assert "Conversation summary" in summary_message
