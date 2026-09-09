# Compact Terminal Conversation UI

## What changed
- **Conversation screen** (`src/susanoox/ui/screens/conversation.py`): added a compact framed welcome view with Susanoox identity, starter actions, truthful shortcuts, and safely rendered project context.
- **Terminal theme** (`src/susanoox/ui/susanoox.tcss`): replaced oversized cards with a restrained transcript-first layout, compact responsive composer, and visible keyboard and mouse focus states.
- **Conversation widgets** (`src/susanoox/ui/widgets/header.py`, `src/susanoox/ui/widgets/messages.py`, `src/susanoox/ui/widgets/prompt.py`): refined header hierarchy, explicit message attribution, prompt guidance, and an accessible Send control.
- **UI tests** (`tests/ui/test_app.py`): added coverage for compact rendering, mouse submission, long project names, literal markup-like paths, and visible controls at `80x24`.

## Why
- The previous interface used large panels and message cards that reduced conversation space and did not match the requested compact coding-agent terminal experience.

## QA checks
- Launch `susanoox` and verify the framed welcome panel, starter actions, model/project context, compact prompt, and shortcut guidance are visible.
- Resize the terminal to `80x24` and verify every starter action and the Send control remain visible, focusable, and clickable.
- Send a prompt with both `Ctrl+Enter` and the Send control, then verify streaming, cancellation, and conversation clearing still work.
- Launch from a project with a long or bracketed directory name and verify the name is shown literally on one ellipsized row.

## Verification
- `.venv/bin/ruff format --check .` — passed; 45 files already formatted.
- `.venv/bin/ruff check .` — passed with no errors.
- `.venv/bin/pyright` — passed with 0 errors and 0 warnings.
- `.venv/bin/pytest -q` — passed; 42 tests passed.
- `.venv/bin/python -m build` — passed; source distribution and wheel built successfully.
- CLI smoke checks — passed for `susanoox --version` and `susanoox --help`.
- `git diff --check` — passed.

## Commit
- `45b4811` — `feat: add compact terminal conversation UI`
