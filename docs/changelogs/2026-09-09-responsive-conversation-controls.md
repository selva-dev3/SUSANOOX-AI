# Responsive Conversation Controls

## What changed
- **Conversation screen** (`src/susanoox/ui/screens/conversation.py`): moved welcome content into the scrollable transcript, added interactive starter prompts, preserved welcome content on clear, and reset transcript scrolling.
- **Responsive application** (`src/susanoox/ui/app.py`): added native Textual horizontal and vertical breakpoints that update through live terminal resizes.
- **Terminal styling** (`src/susanoox/ui/susanoox.tcss`): added starter-button states and compact-height spacing while keeping bottom controls visible.
- **UI regression coverage** (`tests/ui/test_app.py`): added short-terminal, live-resize, starter-action, and long-transcript clear tests.

## Why
- The welcome suggestions appeared interactive but were plain text, while short terminal panes could place the actual prompt and Send button outside the visible viewport.
- Clearing a long transcript could restore the welcome panel at the previous scroll offset, leaving its starter actions off-screen.

## QA checks
- Launch Susanoox in an 80×24 terminal and verify the prompt and Send button remain visible.
- Resize between 80×24 and a larger terminal and verify the shortcut bar and welcome columns adapt immediately.
- Click each starter prompt and verify its text populates the focused prompt input without submitting.
- Create a long conversation, clear it, and verify the welcome panel returns at the top with the first starter action visible.
- Verify sending, cancellation, authentication recovery, and Markdown streaming continue to behave normally.

## Verification
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/ruff format --check ...` — passed.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/ruff check .` — passed with no errors.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pyright` — passed with 0 errors, warnings, or information messages.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q` — passed; 38 tests.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m build` — passed; source distribution and wheel built successfully.
- `git diff --check` for the four scoped files — passed.

## Commit
- `aefef9b` — `fix: keep conversation controls visible and interactive`
