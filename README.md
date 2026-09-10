# Susanoox

Susanoox is an independently designed, full-screen AI coding assistant for the terminal. The
current `0.1.0` milestone provides secure API-key onboarding, live model selection, persistent
multi-turn sessions, explicit planning, bounded automatic project context, rolling conversation
compaction, observable retries, exact API-reported usage, image attachments, live Markdown
streaming, cancellation, and a responsive Textual interface.

> [!IMPORTANT]
> Automatic context selection is read-only. File editing, shell execution, Git mutations, and the
> autonomous tool loop are not enabled in this milestone. Approving a plan continues the AI
> conversation using selected context; it does not pretend to mutate the project.

## Requirements

- Python 3.11 or newer
- Git (required for installation from GitHub)
- Linux, macOS, or Windows
- A Susanoox API key
- An operating-system keyring supported by Python `keyring`, or a process-scoped environment key

## Installation

### 1. Install pipx

Use Python 3.11 or newer for both pipx and Susanoox. With multiple Python installations,
pass `--python /path/to/python3.11-or-newer` to `pipx install`.

**Ubuntu 23.04+ / Debian 12+:**

```bash
sudo apt update
sudo apt install pipx git python3-venv
pipx ensurepath
```

**macOS with Homebrew:**

```bash
brew install python pipx git
pipx ensurepath
```

**Windows PowerShell:** install Python 3.11+ and [Git for Windows](https://git-scm.com/downloads/win),
then run:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
```

Open a new terminal after `ensurepath`, then check `pipx --version` and `git --version`.
For other systems, see the [official pipx installation guide](https://pipx.pypa.io/latest/how-to/install-pipx.html).
If Linux reports `externally-managed-environment`, use its package manager rather than overriding
system Python protections.

### 2. Authenticate for the private repository

This repository is private: your GitHub account must have access to
[`selva-dev3/SUSANOOX-AI`](https://github.com/selva-dev3/SUSANOOX-AI). A Susanoox API key does not
grant GitHub access. Ask the repository owner for an invitation if needed.

For HTTPS installation, install [GitHub CLI](https://cli.github.com/), then authenticate:

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
```

The second command configures Git to use GitHub CLI authentication; see
[`gh auth setup-git`](https://cli.github.com/manual/gh_auth_setup-git).
Use secure credential storage. If GitHub CLI warns that credentials would be saved as plain text,
use an OS-backed Git credential manager or an existing SSH setup instead. Never place tokens in
installation URLs, shell history, or project files.

### 3. Install from main

Run this in a new terminal on Linux, macOS, or Windows:

```bash
pipx install "git+https://github.com/selva-dev3/SUSANOOX-AI.git@main"
susanoox --version
susanoox --help
```

`@main` is intentional: an unqualified Git URL follows the repository's default branch, which
may differ from `main`. You do not need to clone the repository for a pipx installation.

If you already use an SSH key authorized for this repository, use this alternative instead:

```bash
pipx install "git+ssh://git@github.com/selva-dev3/SUSANOOX-AI.git@main"
```

### Update an existing pipx installation

Close Susanoox and reinstall from `main` to pick up new commits even if the package version has
not changed:

```bash
pipx install --force "git+https://github.com/selva-dev3/SUSANOOX-AI.git@main"
susanoox --version
```

For SSH installations, use the SSH URL above with the same `--force` option. This refreshes the
pipx application; it does not delete your project or OS-keyring credentials. `--version` reports
the package version, not a Git commit, so it can remain `0.1.0` after an update.

### Local development (alternative to pipx)

Authenticate as above, then clone `main` explicitly:

```bash
git clone --branch main https://github.com/selva-dev3/SUSANOOX-AI.git
cd SUSANOOX-AI
```

**Linux/macOS:**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/susanoox --version
```

**Windows PowerShell:**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\susanoox.exe --version
```

These commands do not require virtual-environment activation or changes to PowerShell execution
policy. Use `.venv/bin/susanoox` (Windows: `.\.venv\Scripts\susanoox.exe`) to run this checkout.
For an SSH clone, replace the HTTPS clone URL with `git@github.com:selva-dev3/SUSANOOX-AI.git`.

### Installation troubleshooting

- **Repository not found / authentication failed:** confirm that your GitHub account has repository
  access and that HTTPS Git authentication or your SSH key is configured.
- **`susanoox` not found:** run `pipx ensurepath`, reopen the terminal and check `pipx list`; for a
  development checkout, use the explicit executable path above.
- **Wrong or old UI:** reinstall using the explicit `@main` URL; check `command -v susanoox` on
  Linux/macOS or `Get-Command susanoox` in PowerShell for an older executable taking precedence.
- **Unsupported Python / missing venv:** install Python 3.11+ and its venv support, then choose
  that interpreter with pipx's `--python` option or use it to create the development environment.

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

## Access the current intelligence features

Run `susanoox` from the project you want Susanoox to understand. The current features are
available as follows:

| Feature | How to access it |
| --- | --- |
| Plan Mode | Start with `susanoox --plan`, enter `/plan` to toggle it, or use `/plan <task>` |
| Plan decisions | Use `/approve`, `/revise <feedback>`, or `/reject` after a plan appears |
| Automatic context | Enabled by default for text prompts; enter `/context` to inspect selected files |
| Persistent sessions | Run `susanoox sessions`, then resume with `susanoox --resume <id>` |
| Smart summarization | Runs automatically when conversation history reaches its configured threshold |
| Retry recovery | Runs automatically for eligible pre-response failures; press `Esc` to cancel |
| Token usage | Enter `/usage` for exact API-reported usage in the current session |

Plan Mode, automatic context, summarization, and retry behavior can be configured globally or in
`<project>/.susanoox/config.toml`; see [Configuration](#configuration). Automatic context and
summarization do not require separate commands during normal conversation.

## Planning and sessions

Start directly in explicit planning mode:

```bash
susanoox --plan
```

Enter a task to produce a concise visible plan before the conversation continues. Approve it with
`/approve`, request a new version with `/revise <feedback>`, or cancel it with `/reject`. You can
also create a plan at any time with `/plan <task>` or toggle planning with `/plan`. Plans contain
proposed steps and validation intent, never hidden model reasoning. Approval is a terminal plan
decision: it submits the proposal to the conversational model but does not mark individual steps
as executed while project tools are unavailable.

Successful conversations, summaries, plan state, and retry metadata are stored in a versioned
SQLite database under the platform-standard Susanoox user data directory. Credentials and image
bytes are never written to it. List project sessions and resume one by its displayed ID prefix:

```bash
susanoox sessions
susanoox --resume 12ab34cd
```

Older messages remain stored as the recovery source of truth. When the active request approaches
the configured budget, Susanoox sends a structured rolling summary plus recent messages rather
than sending the full conversation indefinitely.

## Automatic project context

For text prompts, Susanoox ranks a bounded set of relevant files using path/content matches,
test relationships, configuration files, and current Git changes. It respects Git ignore rules,
rejects symlinks and binary or oversized files, excludes common credential files and build/cache
directories, and redacts likely credentials from excerpts. Selected repository content is marked
as untrusted data in the model request. Use `/context` after a request to inspect what was selected.

Embedding-based retrieval with `susanoox-embed` is intentionally deferred until the deterministic
local selector has established a safe and measurable baseline.

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

`susanoox-vision` handles images and OCR. Select it with `/model susanoox-vision` or
`susanoox --model susanoox-vision`; attaching an image also selects it automatically.
The provider describes this service as shared TEST/DEV infrastructure, not production traffic.

## Conversation commands

Type `/` at the start of the prompt to show command suggestions; keep typing to filter them.
Use Up/Down to select, then Tab or Enter to insert the command. Press Enter again to run it.
Escape dismisses suggestions without clearing your text. Arguments and ordinary text do not
open the menu.

| Command | Action |
| --- | --- |
| `/model` | Show all models and select an available chat model |
| `/usage` | Show exact token usage reported by the API for the current session |
| `/paste-image` | Attach an image from the operating-system clipboard |
| `/plan [task]` | Toggle plan mode or create a visible plan for a task |
| `/approve` | Approve the current plan and continue |
| `/revise <feedback>` | Create a revised plan version |
| `/reject` | Cancel the current plan without continuing |
| `/context` | Explain the files selected for the last request |
| `/clear` | Clear active conversation context and its persisted summary |
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
desktops, focus the prompt and press **Ctrl+V** to attach a copied image directly.
`/paste-image` also reads an image from the operating-system clipboard.
`Ctrl+Shift+V` also works when the terminal forwards it; many terminals reserve it for text paste. The
attachment is shown before sending and can be removed with the attachment control.

Images are validated before use and limited to 10 MB. Clipboard support depends on the operating
system and installed terminal/clipboard facilities; when it is unavailable, Susanoox displays a
file-path fallback. Image understanding also requires the selected Susanoox chat model and API
deployment to accept OpenAI-compatible image content.
Attaching an image automatically selects `susanoox-vision`. Fast and Large are text-only.
The first vision request after idle may take 10–20 seconds to warm up; the UI stays responsive.
Press Enter to send the image with your text (or alone for a description). Follow-up requests
stay on vision so the image remains available. Remove pending images and `/clear` image history
before switching back to a text-only model. Failed requests restore the draft for an explicit retry.
Use your terminal's normal text-paste gesture for text; Ctrl+V in the composer is image-only.
Some terminals intercept shortcuts, and remote/SSH sessions may not expose your desktop clipboard.
Use `/paste-image` or a local image-file path when direct clipboard access is unavailable.
Known non-vision models are blocked before image requests are sent. Submission waits for image
validation to finish; replaced or cancelled loads cannot overwrite the current attachment.

## Keyboard controls

| Shortcut | Action |
| --- | --- |
| `Enter` | Send the prompt |
| `Shift+Enter` | Insert a new line |
| `Ctrl+V` | Attach an image from the OS clipboard while the prompt is focused |
| `Ctrl+Shift+V` | Image-paste alias if forwarded; often reserved by the terminal for text paste |
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
plan_mode = false
auto_context = true
context_max_files = 12
context_max_chars = 40000
context_max_file_bytes = 1000000
summary_trigger_chars = 48000
summary_recent_messages = 8
api_retry_attempts = 2
retry_base_delay_seconds = 0.5
```

Set `api_retry_attempts = 0` to disable every automatic API retry, including overflow recovery
and empty-response retries.

CLI options override project configuration, which overrides global configuration. Project files
cannot provide API keys or weaken application security rules.

## Security

- Credentials use the OS keyring or an explicit process environment variable.
- Logs redact common credential formats and authorization fields.
- Image payloads are kept in memory and are never written to diagnostic logs.
- Attachments are validated by file signature, format, size, and safe image dimensions.
- In-memory image context is capped at 20 MB; older binary payloads are pruned before newer ones.
- Automatic context cannot leave the detected project root, skips symlinks and common secret files,
  and treats repository content as untrusted.
- Retries are bounded and occur only before public response text is emitted. Authentication,
  permission denial, and ordinary bad requests are not retried.
- The current milestone exposes no file-write, shell, network-tool, or Git mutation authority to
  the model.
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
