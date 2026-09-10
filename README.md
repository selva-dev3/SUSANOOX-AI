# Susanoox

Susanoox is an independently designed, full-screen AI coding assistant for the terminal. The
current `0.1.0` milestone provides secure API-key onboarding, live model selection, multi-turn
conversation, exact API-reported usage, image attachments, live Markdown streaming, cancellation,
and a responsive Textual interface.

> [!IMPORTANT]
> Project inspection, file editing, shell execution, Git mutations, persisted sessions, and the
> autonomous tool loop are planned but are not enabled in this milestone. Susanoox never pretends
> that an unavailable tool ran.

## Requirements

- Python 3.11 or newer
- Linux, macOS, or Windows
- A Susanoox API key
- An operating-system keyring supported by Python `keyring`, or a process-scoped environment key

## Installation

Install from GitHub with `pipx`:

```bash
pipx install git+https://github.com/selva-dev3/SUSANOOX-AI.git
```

For local development:

```bash
git clone https://github.com/selva-dev3/SUSANOOX-AI.git
cd SUSANOOX-AI
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## First run

```bash
susanoox
```

If no credential exists, Susanoox displays a masked API-key prompt and validates the key with an
actual minimal API request. On success, it stores the key in the operating-system credential
manager. Keys are not stored in the project, configuration files, sessions, or logs. On Windows,
the keyring and log directory rely on the current user's profile ACL; on POSIX systems, Susanoox
also restricts its log file to mode `0600`.

If the host has no usable secure keyring, provide a key only to the current process:

```bash
# Linux/macOS
SUSANOOX_API_KEY="..." susanoox

# Windows PowerShell
$env:SUSANOOX_API_KEY="..."; susanoox
```

Avoid adding that command to shell history. Susanoox deliberately refuses a plaintext credential
file fallback.

## Models

The default model is `susanoox-fast`. Select the larger chat model for more complex work:

```bash
susanoox --model susanoox-large
```

Inside the conversation, enter `/model` to open the model picker or use a direct command:

```text
/model susanoox-large
```

`susanoox-embed` is reserved for the future context-retrieval engine and cannot be selected as a
chat model.

## Conversation commands

| Command | Action |
| --- | --- |
| `/model` | Show all models and select an available chat model |
| `/usage` | Show exact token usage reported by the API for the current session |
| `/paste-image` | Attach an image from the operating-system clipboard |
| `/clear` | Clear in-memory conversation context |
| `/help` | Show available commands |
| `/exit` | Exit Susanoox |

If the configured API does not provide usage metadata, `/usage` reports that it is unavailable
instead of estimating token counts.
If any request lacks usage metadata (including a cancelled or failed request), reported totals
are explicitly marked partial. Clearing chat history does not reset session usage.

## Image input

Paste or drag an absolute PNG, JPEG, GIF, or WebP file path into the prompt to attach it.
Relative paths must start with `./` or `../`, or be quoted (for example, `"screen shot.png"`).
Bare filenames and ordinary prose remain text. On supported
desktops, `/paste-image` reads an image directly from the operating-system clipboard.
`Ctrl+Shift+V` also works when the terminal forwards it; many terminals reserve it for text paste. The
attachment is shown before sending and can be removed with the attachment control.

Images are validated before use and limited to 10 MB. Clipboard support depends on the operating
system and installed terminal/clipboard facilities; when it is unavailable, Susanoox displays a
file-path fallback. Image understanding also requires the selected Susanoox chat model and API
deployment to accept OpenAI-compatible image content.
Vision capability for Fast and Large is currently unverified; the attachment status says so.
Known non-vision models are blocked before image requests are sent. Submission waits for image
validation to finish; replaced or cancelled loads cannot overwrite the current attachment.

## Keyboard controls

| Shortcut | Action |
| --- | --- |
| `Enter` | Send the prompt |
| `Shift+Enter` | Insert a new line |
| `Ctrl+Shift+V` | Attach an image from the OS clipboard |
| `Esc` | Cancel the active response |
| `Ctrl+K` | Clear in-memory conversation context |
| `Ctrl+Q` | Exit |

The prompt supports multiple lines. Messages render Markdown and highlighted code blocks.

## Configuration

Susanoox reads optional TOML configuration from the platform-specific user configuration folder
and `<project>/.susanoox/config.toml`:

```toml
[susanoox]
model = "susanoox-fast"
request_timeout_seconds = 60
```

CLI options override project configuration, which overrides global configuration. Project files
cannot provide API keys or weaken application security rules.

## Security

- Credentials use the OS keyring or an explicit process environment variable.
- Logs redact common credential formats and authorization fields.
- Image payloads are kept in memory and are never written to diagnostic logs.
- Attachments are validated by file signature, format, size, and safe image dimensions.
- In-memory image context is capped at 20 MB; older binary payloads are pruned before newer ones.
- The current conversation milestone exposes no filesystem, shell, network-tool, or Git authority
  to the model.
- Future tools will be constrained to the project and mediated by a centralized approval policy.

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## Troubleshooting

**Secure credential storage is unavailable:** configure a supported keyring backend or use the
process-scoped `SUSANOOX_API_KEY` fallback.

**Authentication fails:** confirm the key is active and the Susanoox service is reachable. The
endpoint is intentionally omitted from terminal errors. Retry from the onboarding screen.

**The UI has limited color:** use a terminal with true-color support. The layout remains usable on
narrow and reduced-color terminals.

Redacted diagnostic logs are stored in the platform-standard user log directory. Run with
`susanoox --debug` for additional diagnostics.

## Development checks

```bash
ruff format --check .
ruff check .
pyright
pytest
python -m build
```

No real API key is required by the automated test suite.

## License

MIT License. See [LICENSE](LICENSE).
