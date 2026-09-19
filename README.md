# chat-bridge-mcp

> **Status:** `0.1.0` — early development; the 6-tool MCP surface and base wire-up are
> in place but several HIGH/MEDIUM review findings are still open. No stable
> release scheduled yet. See [CHANGELOG.md](CHANGELOG.md) for the v0.1.0
> inventory and `docs/superpowers/specs/2026-09-16-chat-bridge-design.md` for
> the design contract.

A standalone Bodai MCP server in the [Bodai registry](https://github.com/lesleslie/mahavishnu/blob/main/BODAI_REPO_REGISTRY.md).
Lets one Claude Desktop and one ChatGPT Desktop, running on the same machine,
converse with each other through the bridge by driving each app's currently-active
chat via Chrome DevTools Protocol.

**6-tool MCP surface** (`ask_chatgpt`, `ask_claude`, `forward_chatgpt`,
`forward_claude`, `list_peers`, `get_peer_health`) over Streamable HTTP on port 3057,
plus the 4 Bodai baseline tools (`discover_tools`, `get_liveness`, `get_readiness`,
`health_check_all`).

**OS support:** macOS and Windows are fully supported. Linux works against
community-built Electron desktop apps (Anthropic and OpenAI do not ship
official Linux builds), but the shipped selector YAML has only `darwin:`
and `windows:` blocks — Linux operators must add a `linux:` block (see
[Quick start](#quick-start)).

## Quick start

The bridge drives each desktop app via Chrome DevTools Protocol (CDP), so
**each desktop app must be running with `--remote-debugging-port=PORT` BEFORE
the bridge starts**. Default ports: **9229** for Claude, **9230** for
ChatGPT. Override via env vars `CHAT_BRIDGE_MCP_CDP_CLAUDE_PORT` and
`CHAT_BRIDGE_MCP_CDP_CHATGPT_PORT` if you need to remap.

### Step 1 — Install chat-bridge-mcp

Same command on macOS, Windows, and Linux (requires Python ≥ 3.14 and
[`uv`](https://docs.astral.sh/uv/)):

```bash
git clone https://github.com/lesleslie/chat-bridge-mcp
cd chat-bridge-mcp
uv sync --extra dev
```

### Step 2 — Launch each desktop app with CDP enabled

#### macOS (darwin)

Official apps: `/Applications/Claude.app` and `/Applications/ChatGPT.app`.

**One-shot launch** (re-run each session):

```bash
open -a "Claude" --args --remote-debugging-port=9229
open -a "ChatGPT" --args --remote-debugging-port=9230
```

**Persistent launch** so CDP survives every login — wrap the commands in
a shell script and add it as a login item (`System Settings → General →
Login Items → +`):

```bash
#!/usr/bin/env bash
# ~/bin/launch-cdp-desktops.sh
open -a "Claude" --args --remote-debugging-port=9229
open -a "ChatGPT" --args --remote-debugging-port=9230
```

```bash
chmod +x ~/bin/launch-cdp-desktops.sh
```

**Verify CDP is listening:**

```bash
curl -s http://127.0.0.1:9229/json/version | jq .webSocketDebuggerUrl
curl -s http://127.0.0.1:9230/json/version | jq .webSocketDebuggerUrl
```

#### Windows 10 / 11

Official apps (paths vary by installer version; common locations shown):

- **Claude Desktop** — `%LOCALAPPDATA%\AnthropicClaude\claude.exe`
  (verify with `where claude` from PowerShell).
- **ChatGPT Desktop** — `%LOCALAPPDATA%\Programs\ChatGPT\ChatGPT.exe`
  (verify with `where chatgpt`).

**One-shot launch** (PowerShell):

```powershell
& "$env:LOCALAPPDATA\AnthropicClaude\claude.exe" --remote-debugging-port=9229
& "$env:LOCALAPPDATA\Programs\ChatGPT\ChatGPT.exe" --remote-debugging-port=9230
```

**Persistent launch** (recommended for bridge operators):

1. Right-click `claude.exe` → **Create shortcut**.
2. Right-click the shortcut → **Properties** → **Shortcut** tab.
3. Append `--remote-debugging-port=9229` to the **Target** field so it
   reads `"...claude.exe" --remote-debugging-port=9229`.
4. Repeat for `ChatGPT.exe` with `--remote-debugging-port=9230`.
5. Move both shortcuts into the Startup folder: press `Win+R`, type
   `shell:startup`, press Enter, drop the shortcuts there.

**Verify CDP is listening** (PowerShell):

```powershell
(Invoke-WebRequest http://127.0.0.1:9229/json/version).Content
(Invoke-WebRequest http://127.0.0.1:9230/json/version).Content
```

#### Linux (community builds only)

> **Note:** Anthropic and OpenAI do not ship official Claude Desktop or
> ChatGPT Desktop builds for Linux. Linux users run community packages
> (e.g., `claude-desktop` from the AUR on Arch, or third-party Electron
> wrappers for ChatGPT). The bridge code itself is cross-platform Python,
> but the shipped selector YAML has only `darwin:` and `windows:` blocks —
> **Linux operators must add a `linux:` block to `settings/selectors.yaml`
> before starting the bridge** (template below).

**Persistent launch** via `.desktop` file — append `--remote-debugging-port`
to the `Exec=` line:

```bash
# Edit Claude Desktop launcher
sudo sed -i 's|^Exec=.*|& --remote-debugging-port=9229|' \
    /usr/share/applications/claude-desktop.desktop

# Edit ChatGPT Desktop launcher
sudo sed -i 's|^Exec=.*|& --remote-debugging-port=9230|' \
    /usr/share/applications/chatgpt-desktop.desktop
```

**One-shot launch** by running the underlying Electron binary directly:

```bash
/path/to/claude-desktop --remote-debugging-port=9229 &
/path/to/chatgpt-desktop --remote-debugging-port=9230 &
```

**Verify CDP is listening:**

```bash
curl -s http://127.0.0.1:9229/json/version
curl -s http://127.0.0.1:9230/json/version
```

**Required `linux:` block for `settings/selectors.yaml`** (CSS selectors
are usually identical to the `windows:` block since both Electron apps
render the same DOM across platforms — verify against your installed app):

```yaml
linux:
  claude:
    input_box:               "[contenteditable='true'][data-testid='composer-input']"
    send_button:             "button[aria-label='Send']"
    response_container:      "[data-message-author='assistant']"
    stop_generating_indicator: "button[aria-label='Stop response']"
  chatgpt:
    input_box:               "textarea#prompt-textarea"
    send_button:             "button[data-testid='send-button']"
    response_container:      "[data-message-author-role='assistant']"
    stop_generating_indicator: "button[aria-label='Stop generating']"
```

After both desktop apps are running and CDP is verified, **sign into the
chat you want each app to drive and ensure it is the currently-active
chat window** — the bridge targets whichever chat is in the foreground.

### Step 3 — Start the bridge

Same command on every platform:

```bash
uv run chat-bridge-mcp start
```

Expect stdout logs showing two `attach succeeded` lines (one per peer).
If a peer fails to attach, the bridge stderr will surface a
`PeerNotAttachedError` — most commonly the CDP port isn't listening yet
or the chat window isn't focused.

## First-install manual smoke-test (mandatory)

The e2e tier cannot exercise the React-controlled-input event trick the bridge
relies on. Verify the bridge is functional against your actual Claude Desktop
and ChatGPT Desktop by running these steps. **If any step fails, do not deploy.**

1. **Bridge startup.** From one terminal: `uv run chat-bridge-mcp start`. From
   another: `curl -s http://127.0.0.1:3057/health | jq`. Expect 200 with at least
   one peer in `extra_components` (entities_count >= 1). If both peers failed
   to attach, /health returns 503 with entities_count == 0 for both — see
   [Concurrency](#concurrency--known-v1-limitations) for the per-peer
   collision contract.
2. **`ask_chatgpt("Reply with the word 'pong'.")`** — expect "pong" within
   `streaming_timeout_seconds` (default 180s). The bridge types the prompt
   into ChatGPT Desktop's currently-active chat, presses Enter, and polls
   until streaming finishes.
3. **`forward_chatgpt("claude", "What is 2+2?", ask_for_opinion=True)`** —
   inspect the bridge's stdout/log for a line containing `<<nonce=...>>`
   twice (paired markers from the guardrail template). ChatGPT's reply will
   quote the wrapped text but treat it as data, not instructions.
4. **`ask_claude(...)` and `forward_claude(...)`** — symmetric against
   Claude Desktop.
5. **`list_peers()` and `get_peer_health("chatgpt")`** — both should return
   JSON with the four-signal `HealthFeedState`:
   - `entities_count >= 1` (peer is attached)
   - `cycles_total >= 1` (at least one successful round trip)
   - `errors_total == 0` (no failures)
   - `last_updated_timestamp` (ISO-8601 string, refreshes on each call)

If any step fails, do not deploy — open an issue with the bridge subprocess
stderr and the failing step's chat-surface error string.

## Concurrency — known v1 limitations

Per spec §5.6, the bridge does NOT serialize concurrent calls to the same peer.
Two concurrent `ask_chatgpt` calls produce **prompt-drop data corruption**: both
calls end up returning the second call's reply because they share the input
box and the second Enter overrides the first. The integration test
`test_concurrent_calls_pin_drop` pins this contract by name. If you need
per-call isolation, sequence calls explicitly.

Per spec §5.6, the WebSocket leak under concurrent first-time callers is
documented as a v1 limitation in `peers/base.py`. The leak is cosmetic on
subprocess shutdown (the OS reaps the unclosed file descriptor); the v0.2.0
fix is per-call WS lifecycle (open in `_send_uncounted`, close in `finally`).

## Quality & CI

This server uses [Crackerjack](https://github.com/lesleslie/crackerjack) for
repo-wide quality gates. Run `uv run crackerjack run` for full validation.

### Test tiers

The test suite follows the standard pyramid:

- **Unit tests** — `<1s/test`, ~30 tests. Run by default.
- **Integration tests** — `~5s/test`, exercise the FastMCP tool surface
  with stubbed peers. Run by default.
- **End-to-end tests** — `~30s/test`, gated by `CHAT_BRIDGE_MCP_E2E=1`.
  Drives a headless Electron fixture that approximates Claude Desktop /
  ChatGPT Desktop. **Skipped by default** because it does not exercise the
  real React-controlled-input event trick the bridge relies on (see §8.4
  smoke-test protocol above for the gate that *does*).

```bash
# Default suite (unit + integration, ~30s):
unset VIRTUAL_ENV && .venv/bin/pytest --cov=chat_bridge_mcp --cov-report=term-missing -m "not e2e"

# E2E suite (requires the Electron fixture):
unset VIRTUAL_ENV && CHAT_BRIDGE_MCP_E2E=1 .venv/bin/pytest -m e2e
```

Coverage floor is set by Crackerjack (`--cov-fail-under`); see `pyproject.toml`
for the current value.

### End-to-end gating

The e2e tier is intentionally opt-in:

- It is **not** part of the default CI run (single-platform fixture).
- It **does not** replace the manual first-install smoke-test protocol
  above. Operators must run that against real Claude Desktop and
  ChatGPT Desktop before deploying v1.0.0.

## Documentation standards

See [Catalog README](https://github.com/lesleslie/www-mcp-servers) for the
documentation standards each fleet member follows. Production source in this
repo follows the conventions below; pull requests that violate them are
rejected at review.

- `from __future__ import annotations` is the first non-comment line of every
  source file.
- Type hints use modern syntax: `X | None` (not `Optional[X]`),
  `list[str]` / `dict[str, int]` (not `List[...]` / `Dict[...]`),
  `pathlib.Path` for filesystem paths.
- Function arguments with default `None` are typed `X | None = None`
  (no implicit-optional).
- No `Any` in tool inputs, return types, or orchestration state — escape
  through `TYPE_CHECKING` and a typed protocol when needed.
- Logging uses the Oneiric logger — never `print()`, never stdlib `logging`.
- No `assert` in production code under `chat_bridge_mcp/`; raise from the
  `chat_bridge_mcp.exceptions` hierarchy.
- All I/O in the orchestration layer is async. No blocking calls
  (`time.sleep`, sync HTTP, sync file I/O) inside async functions.
- Source files are organized by domain (`cdp.py`, `peers/`, `_tools.py`,
  `server.py`, ...); see the spec §10a file map for the canonical layout.

## Repository layout

```
chat_bridge_mcp/          # Production package
  __main__.py             # Typer CLI entry point
  server.py               # FastMCP singleton + ChatBridgeServer lifecycle
  _tools.py               # @mcp.tool() decorators + _clients registry
  cdp.py                  # CDPConnection / CDPSession over websockets
  config.py               # ChatBridgeConfig + DEFAULT_PORT
  selectors.py            # SelectorSet + load_selectors
  guardrail.py            # Nonce-protected wrap for forward_*
  peers/                  # ClaudeDesktopAdapter + ChatGPTDesktopAdapter
settings/                 # Operational YAML (selectors, etc.)
tests/                    # unit/, integration/, e2e/ tiers
docs/superpowers/         # Spec + implementation plan
```

## License

Internal-first; license terms are tracked in the
[`www-mcp-servers`](https://github.com/lesleslie/www-mcp-servers) catalog.
