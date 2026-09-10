# Vision Model and Clipboard Image Input

## What changed
- **Model configuration** (`src/susanoox/config/settings.py`, `src/susanoox/models/catalog.py`): added `susanoox-vision` and marked Fast and Large as text-only models.
- **Clipboard composer** (`src/susanoox/ui/widgets/prompt.py`, `src/susanoox/ui/screens/conversation.py`): added direct Ctrl+V image attachment, automatic vision selection, warm-up status, and guarded model switching.
- **Authentication recovery** (`src/susanoox/ui/app.py`, `src/susanoox/conversations/service.py`): preserved committed conversation and image context while restoring failed requests after authentication renewal.
- **Tests and documentation** (`tests/ui/test_vision.py`, `tests/ui/test_app.py`, `tests/unit/test_client.py`, `tests/unit/test_settings.py`, `README.md`): documented image workflows and covered vision selection, retries, follow-ups, and authentication recovery.

## Why
- Image requests were routed to text-only models, which rejected OpenAI-compatible multimodal content with HTTP 400.
- A copied image could not be attached directly from the focused conversation input with Ctrl+V.
- Retrying after failures could duplicate visible turns or lose prior image context during authentication renewal.

## QA checks
- Copy a PNG, JPEG, GIF, or WebP image, focus the prompt, press Ctrl+V, and verify `susanoox-vision` is selected without sending automatically.
- Enter an image question, press Enter, and verify the streamed response remains responsive during the initial model warm-up.
- Send a follow-up about the same image and verify the prior image remains in conversation context.
- Verify `/paste-image` and image-file-path attachment remain available when the terminal does not forward Ctrl+V.
- Verify failed and authentication-expired requests restore the draft without duplicating or automatically resending it.
- Verify `/clear` permits switching from vision back to a text-only model.

## Verification
- `.venv/bin/ruff check .` — passed.
- `.venv/bin/ruff format --check .` — passed; 62 files already formatted.
- `.venv/bin/pyright` — passed with 0 errors, 0 warnings, and 0 informations.
- `.venv/bin/python -m pytest -q` — passed; 95 tests passed.
- `.venv/bin/python -m build --outdir /tmp/susanoox-vision-context-build` — passed; wheel and source distribution built.
- `git diff --check` — passed.
- Live `susanoox-vision` request — not run; requires explicit approval and may consume shared service resources.

## Commit
- `a49c65a` — `feat: add vision model and clipboard image input`
