# Stable List Streaming and Cancellation

## What changed
- **Message rendering** (`src/susanoox/ui/widgets/messages.py`): render Rich Markdown in one stable Textual panel instead of rebuilding Markdown child widgets.
- **Stream lifecycle** (`src/susanoox/ui/streaming.py`, `src/susanoox/ui/screens/conversation.py`): retain rendered snapshots, distinguish pending timers from active callbacks and guard cancellation-status updates during teardown.
- **Regressions** (`tests/unit/test_streaming.py`, `tests/ui/test_list_streaming.py`): cover slow lists, stable widget identity, styled code, follow-up messages, cancellation and shutdown.

## Why
- Cancelling a timed Markdown update could propagate into Textual widget-removal tasks and stop the application; indefinitely shielding updates would instead stall cancellation.

## QA checks
- Request numbered and nested lists of at least 30 items; verify streaming completes and a follow-up message works.
- Press Escape during streaming, then send another message; verify prompt usability and cancellation status.
- Quit while a list streams; verify shutdown does not hang.
- Request fenced Python code and verify code styling, list formatting and scrolling.
- Textual Markdown-specific link interaction is no longer provided by the stable Rich-backed panel.

## Verification
- Isolated staged snapshot: `.venv/bin/python -m pytest -q` with snapshot `PYTHONPATH` — 85 passed in 23.10s, including unchanged stuck-render cancellation tests.
- `.venv/bin/ruff check .` — passed; `.venv/bin/ruff format --check .` — 55 files formatted.
- `.venv/bin/pyright` — 0 errors, 0 warnings.
- `python -m build` — not run separately for this intermediate snapshot; combined working-tree build previously passed.
- `git diff --cached --check` — passed; staged secret-pattern scan — no matches.
- Independent review — passed with no actionable findings; live API testing — not run.

## Commit
- `78c432b` — `fix: prevent list streaming exits and cancellation hangs`
