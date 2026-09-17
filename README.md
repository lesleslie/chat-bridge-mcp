# chat-bridge-mcp

> **Status:** `draft` — v1.0.0 release candidate pending review (see [spec](docs/superpowers/specs/2026-09-16-chat-bridge-design.md) §13 / Plan-to-spec tracking).

A standalone MCP server in the [`www-mcp-servers`](https://github.com/lesleslie/www-mcp-servers) fleet.
Lets one Claude Desktop and one ChatGPT Desktop, running on the same machine,
converse with each other through the bridge by driving each app's currently-active
chat via Chrome DevTools Protocol.

**v1.0.0 ships a 6-tool MCP surface** (`ask_chatgpt`, `ask_claude`, `forward_chatgpt`,
`forward_claude`, `list_peers`, `get_peer_health`) over Streamable HTTP on port 3057.

## Quick start

```bash
# Install
git clone https://github.com/lesleslie/chat-bridge-mcp
cd chat-bridge-mcp
uv sync --group dev

# Pin --remote-debugging-port in each desktop's shortcut
#   macOS:  edit /Applications/Claude.app and /Applications/ChatGPT.app launchers
#            to include --remote-debugging-port=9229 / --remote-debugging-port=9230
#   Win:    Properties > Target = "...Claude.exe" --remote-debugging-port=9229

# Launch each desktop app normally (double-click).
# Verify each is the currently-active chat you expect.

# Start the bridge
uv run python -m chat_bridge_mcp start
```

## First-install manual smoke-test (mandatory)

The e2e tier cannot exercise the React-controlled-input event trick the bridge
relies on. Verify the bridge is functional against your actual Claude Desktop
and ChatGPT Desktop by running these steps. **If any step fails, do not deploy.**

[Full smoke-test protocol here — see spec §8.4 for the canonical sequence.]

1. `ask_chatgpt("Reply with the word 'pong'.")` — expect "pong" within 180s.
2. `forward_chatgpt("claude", "What is 2+2?", ask_for_opinion=True)` —
   inspect log line for nonce-marked framing.
3. `ask_claude(...)` and `forward_claude(...)` — symmetric.
4. `list_peers()` and `get_peer_health("chatgpt")` — verify counters.
5. `/health` — verify `entities_count >= 1`, `errors_total == 0`.

## Quality & CI

This server uses [Crackerjack](https://github.com/lesleskie/crackerjack) for
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
