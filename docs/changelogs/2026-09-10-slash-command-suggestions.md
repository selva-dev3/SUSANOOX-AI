# Slash-Command Suggestions

## What changed
- **Suggestion menu** (`src/susanoox/ui/widgets/command_suggestions.py`): filter commands from the shared registry and display descriptions or an empty state.
- **Prompt integration** (`src/susanoox/ui/widgets/prompt.py`, `src/susanoox/ui/screens/conversation.py`, `src/susanoox/ui/susanoox.tcss`): show a bounded menu above the prompt and handle keyboard selection, insertion and dismissal.
- **Documentation and tests** (`README.md`, `tests/ui/test_command_suggestions.py`): document shortcuts and test normal/narrow terminals, arguments, multiline text, paths and ordinary chat.

## Why
- Users had to remember slash commands without suggestions while typing.

## QA checks
- Type `/`; verify all commands appear. Type `mo`; verify only `/model` remains.
- Use Up/Down to select and Tab or Enter to insert; verify insertion does not execute and focus stays in the prompt.
- Press Enter again to execute; verify the model picker opens for `/model`.
- Press Escape to dismiss without clearing text; verify arguments, ordinary prose and pasted paths do not open suggestions.
- Resize to a narrow terminal; verify suggestions stay above the prompt and scroll when constrained.
- Menu acceptance is keyboard-operated; mouse acceptance is not implemented.

## Verification
- `env PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q` — 88 passed in 27.39s.
- `.venv/bin/ruff check .` — passed; `.venv/bin/ruff format --check .` — passed.
- `.venv/bin/pyright` — 0 errors, 0 warnings.
- `.venv/bin/python -m build --outdir <temporary-directory>` — source distribution and wheel built successfully.
- `git diff --cached --check` — passed; staged secret-pattern scan — no matches.
- Independent review — passed with no actionable findings; live API testing — not run.

## Commit
- `6de2971` — `feat: add slash command suggestions`
