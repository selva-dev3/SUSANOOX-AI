# Conversation Controls and Image Attachments

## What changed
- **Commands and models** (`src/susanoox/commands.py`, `src/susanoox/models/`, `src/susanoox/conversations/service.py`): added model selection, API-reported usage, image serialization and bounded attachment validation.
- **Conversation UI** (`src/susanoox/ui/screens/`, `src/susanoox/ui/widgets/`, `src/susanoox/ui/susanoox.tcss`): added Enter submission, model picker, terminal branding and cancellable attachment loading.
- **Documentation and tests** (`README.md`, `pyproject.toml`, `tests/`): documented controls, added Pillow and covered feature/error paths.

## Why
- Users could not switch models interactively, inspect token usage or attach images in the existing chat interface.

## QA checks
- Send a message with Enter; verify Shift+Enter inserts a newline.
- Run `/model`, select Fast or Large, and verify the header changes; embeddings must remain unavailable for chat.
- Run `/usage` after requests; missing usage must be identified as unavailable or partial.
- Paste an absolute image path or use `/paste-image`; verify preview label, removal, oversized/invalid-file rejection and cancellation.
- Verify `/clear`, ordinary text paste and multi-turn conversation; actual image understanding requires deployment vision support.

## Verification
- Isolated staged snapshot: `.venv/bin/python -m pytest -q` with snapshot `PYTHONPATH` — 76 passed in 17.75s.
- `.venv/bin/ruff check .` — passed; `.venv/bin/ruff format --check .` — 54 files formatted.
- `.venv/bin/pyright` — 0 errors, 0 warnings.
- `python -m build` — not run separately for this intermediate snapshot; final combined working-tree build previously passed.
- `git diff --cached --check` — passed; staged secret-pattern scan — no matches.
- Native clipboard across all platforms and live API vision — not run.

## Commit
- `7c57636` — `feat: add conversation controls and image attachments`
