from susanoox.security.redaction import redact_secrets


def test_redacts_known_and_structured_secrets() -> None:
    message = "Authorization: Bearer top-secret api_key=key-123456789 known-value"

    redacted = redact_secrets(message, ["known-value"])

    assert "top-secret" not in redacted
    assert "key-123456789" not in redacted
    assert "known-value" not in redacted
    assert redacted.count("[REDACTED]") == 3


def test_redacts_quoted_json_and_configuration_secret_fields() -> None:
    message = '{"api_key":"custom-value", "password": "hunter2", token=plain}'

    redacted = redact_secrets(message)

    assert "custom-value" not in redacted
    assert "hunter2" not in redacted
    assert "plain" not in redacted
    assert redacted.count("[REDACTED]") == 3
