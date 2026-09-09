from susanoox.security.redaction import redact_secrets


def test_redacts_known_and_structured_secrets() -> None:
    message = "Authorization: Bearer top-secret api_key=key-123456789 known-value"

    redacted = redact_secrets(message, ["known-value"])

    assert "top-secret" not in redacted
    assert "key-123456789" not in redacted
    assert "known-value" not in redacted
    assert redacted.count("[REDACTED]") == 3
