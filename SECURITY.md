# Security Policy

## Supported versions

Security fixes are applied to the latest release on the default branch while Susanoox is in alpha.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private vulnerability
reporting feature for this repository and include reproduction steps, affected versions, and the
potential impact. Do not include real API keys or other secrets in the report.

## Credential handling

Susanoox stores API keys through the operating-system credential manager. When that facility is
unavailable, users may provide `SUSANOOX_API_KEY` to the current process; Susanoox does not silently
fall back to plaintext credential files. Application logs apply secret redaction, but users should
still review diagnostics before sharing them.
