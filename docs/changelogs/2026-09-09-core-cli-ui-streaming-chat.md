# Core Susanoox CLI, UI, and Streaming Chat

## What changed
- **CLI and packaging** (`pyproject.toml`, `src/susanoox/cli.py`): added the installable `susanoox` executable, typed package metadata, model selection, and explicit future-session command handling.
- **Terminal application** (`src/susanoox/ui/`, `src/susanoox/app/application.py`): added the responsive Textual onboarding and conversation experience with Markdown streaming, activity states, cancellation, and keyboard controls.
- **Authentication and models** (`src/susanoox/config/credentials.py`, `src/susanoox/models/client.py`): added OS-keyring credential handling, environment-key support, real API validation, safe failures, and OpenAI-compatible streaming.
- **Conversation lifecycle** (`src/susanoox/conversations/service.py`, `src/susanoox/ui/streaming.py`): added multi-turn in-memory context, bounded rendering, deterministic stream cleanup, and retryable empty-response handling.
- **Quality and delivery** (`tests/`, `.github/workflows/`): added unit and UI coverage plus lint, type-check, test, build, and tagged-release workflows.

## Why
- The repository did not contain an installable, secure, full-screen Susanoox terminal client capable of authenticating and streaming multi-turn AI conversations.

## QA checks
- Launch `susanoox` without a configured key and verify the masked onboarding screen, project path, model, and exit shortcut.
- Enter an invalid API key and verify authentication fails without exposing or persisting the key as plaintext.
- Enter a valid API key and verify the conversation screen streams Markdown while remaining responsive to cancellation.
- Send multiple prompts and verify conversation context is retained; cancel a partial response and verify it is excluded from later context.
- Resize the terminal and verify the layout remains usable at narrow and wide dimensions.

## Verification
- `.venv/bin/ruff format --check .` — passed; 43 files formatted.
- `.venv/bin/ruff check .` — passed with no errors.
- `.venv/bin/pyright` — passed with 0 errors, warnings, or information messages.
- `.venv/bin/pytest -q` — passed; 33 tests.
- `.venv/bin/python -m build` — passed; source distribution and wheel built successfully.
- Installed-wheel version and UI-resource smoke check — passed.
- Live API validation — not run; no real API key was available.
- `git diff --check` — passed.

## Commit
- `899a9b1` — `feat: add core Susanoox CLI UI and streaming chat`
