# Contributing to Susanoox

Use Python 3.11 or newer and install the development dependencies with
`python -m pip install -e ".[dev]"`.

Before submitting a change, run:

```bash
ruff format --check .
ruff check .
pyright
pytest
python -m build
```

Keep changes focused, add tests for changed behavior, and never include API keys, `.env` files,
session data, credentials, or private logs. Use Conventional Commit messages.
