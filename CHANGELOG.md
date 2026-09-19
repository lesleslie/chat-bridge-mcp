# Changelog

All notable changes to chat-bridge-mcp are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres
to [Semantic Versioning](https://semver.org/) within Bodai's pre-1.0 convention
(surface additions are minor; wire-up fixes are patch; spec-breaking changes
are major).

## [0.2.0] - 2026-09-19

### Added

- Bootstrap chat-bridge-mcp package skeleton with CLI entry point
- chat-bridge-mcp: Add async WebSocket CDP client (Task 6)
- chat-bridge-mcp: Add BridgeError exception hierarchy (Task 2)
- chat-bridge-mcp: Add ChatBridgeConfig + DEFAULT_PORT (Task 3)
- chat-bridge-mcp: Add ChatGPTDesktopAdapter (Task 9)
- chat-bridge-mcp: Add ClaudeDesktopAdapter (Task 8)
- chat-bridge-mcp: Add nonce-protected guardrail wrap (Task 5)
- chat-bridge-mcp: Add peer adapter base (Task 7)
- chat-bridge-mcp: Add SelectorSet + load_selectors YAML loader (Task 4)
- chat-bridge-mcp: Add server.py skeleton + module-level mcp singleton (Task 11a)
- chat-bridge-mcp: Wire server lifecycle + /health + factory + integration tests (Task 11b)
- server: Register Bodai baseline tools (discover_tools/get_liveness/get_readiness/health_check_all) (T21)
- tools: Add ask_claude MCP tool (T16)
- tools: Add forward_chatgpt MCP tool (T17)
- tools: Add list_peers MCP tool (T19)

### Changed

- Cross-llm-mcp → chat-bridge-mcp (directory, files, all references)

### Fixed

- chat-bridge-mcp: Rename selectors.yaml 'macos' to 'darwin' (T4 bug)
- peers: Guard _ensure_session with asyncio.Lock to fix WS-leak race (T24)
- peers: Include timeout in StreamingTimeoutError context (T23)
- peers: Move sync YAML I/O off the event loop via asyncio.to_thread (T25)
- pyproject+types: Add license/authors/classifiers/urls + tool config + coverage gate (T20)
- Resolve crackerjack comprehensive-hook failures (creosote + linkcheckmd + refurb)
- Resolve crackerjack fast-hook failures (ruff + check-local-links)
- Revert "fix(peers): guard _ensure_session with asyncio.Lock to fix WS-leak race (T24)"
- tools: Catch Exception not BaseException so CancelledError propagates (T26)
- tools: Implement spec §5.1.a — system prompt + empty-question validation (T20a)

### Documentation

- Add CLAUDE.md + AGENTS.md + CHANGELOG.md (T32+T33)
- Implementation plan for cross-llm-mcp
- Mark chat-bridge-mcp implementation plan complete (T34 partial)
- plan: Apply round-3 criticals (Task 3 env vars, Task 7 feed API, Tasks 8/9 cdp_port + entities_count, Tasks 10/11 split into 11a + 11b)
- plan: Apply round-5 criticals (errors-as-content, Literal, prompt→question, errors_total increment, load_config signature, extra_components=[], duplicate server.py)
- plans: Add PLAN_INDEX.md and mark cross-llm-mcp impl plan active
- readme: Align with v0.1.0 status, fix URL typo, document concurrency + HealthFeedState 4-signal (T31)
- README: Package overview + first-install manual smoke-test protocol (Task 15)
- readme: Per-platform install + CDP-launch instructions (mac/win/linux)
- spec: Apply multi-agent review findings to cross-llm-mcp design
- spec: Apply round-2 review findings (python + docs lenses)
- spec: Fix stale cross_llm_mcp.factories import (python-pro round-3 C3)
- spec: Flip status draft -> complete after approval
- spec: Initial design for cross-llm-mcp — CDP bridge between Claude Desktop and ChatGPT Desktop
- Tick all 75 checkboxes + end-of-plan v0.1.0 status note

### Testing

- Cover streaming-timeout, peer edge cases, and server lifecycle (T27-T29)
- Headless Electron fixture + gated e2e test (Task 14)
- integration: Pin list_peers roster round-trip (T19)
- Pin chat-surface error strings for 6 BridgeError subclasses (Task 13)
- Push coverage to 100% (Phase 2)
- TestSelectorsYamlSchemaStable guard for v1.0.0 ship gate (Task 12)
- tools: Pin forward_chatgpt MCP tool surface (T17)

## [0.1.0] - 2026-09-17

### Added

- 6-tool MCP surface: `ask_chatgpt`, `ask_claude`, `forward_chatgpt`,
  `forward_claude`, `list_peers`, `get_peer_health` (Streamable HTTP on
  port 3057).
- 4 Bodai baseline tools: `discover_tools`, `get_liveness`, `get_readiness`,
  `health_check_all`.
- Chrome DevTools Protocol (CDP) driver layer: `chat_bridge_mcp/cdp.py`
  (CDPConnection, CDPSession; WebSocket via `websockets>=11`).
- Peer adapters: `chat_bridge_mcp/peers/{claude,chatgpt}.py` — lazy WS open
  on the caller's event loop, 4-signal `HealthFeedState` per peer.
- Guardrail: `chat_bridge_mcp/guardrail.py` — `wrap(source_reply, *,
  source_peer, ask_for_opinion=True)` with per-call `secrets.token_urlsafe(32)`
  nonce and `<<nonce=base64>>` paired markers.
- Selectors: `chat_bridge_mcp/selectors.py` + `settings/selectors.yaml`
  (darwin + windows blocks; REQUIRED_KEYS = input_box, send_button,
  response_container).
- CLI: `chat-bridge-mcp` console script wired to
  `chat_bridge_mcp.__main__:main`.

### Wire-up fixes (this version)

- **`pydantic-settings~=2.6` added** to runtime deps (was missing →
  `ModuleNotFoundError` on first import).
- **`pyproject.toml` metadata** complete: `description`, `license = {text = "MIT"}`,
  `authors`, `classifiers` (incl. Python 3.14), `[project.urls]`.
- **`[tool.ruff]` / `[tool.mypy]` / `[tool.crackerjack]` / `[tool.coverage.*]`**
  config blocks now present (crackerjack `run` can invoke its gates).
- **`--cov-fail-under=89`** enforcement active in `[tool.pytest.ini_options]`.
- **Strict mypy clean** (was surfacing type errors in `server.py:80,88`,
  `config.py:81`, `cdp.py:22,104`, `_tools.py` 6 unused suppressions — all fixed).
- **`StreamingTimeoutError` raise sites carry `context={"timeout": timeout}`**
  at all 4 sites in `peers/{claude,chatgpt}.py` (chat-surface string
  now reports the actual budget instead of `?`).
- **`except BaseException` → `except Exception`** at 7 sites in `_tools.py`
  (asyncio `CancelledError` propagates correctly per spec §5.6).
- **Sync YAML I/O off the event loop** via `asyncio.to_thread` in both
  peer adapters' `attach()`.

### Spec deviation closed (T20a)

- `ask_chatgpt` and `ask_claude` now match spec §5.1.a signature:
  `async def ask_chatgpt(question: str, system: str | None = None) -> str`.
- Empty `question` validation returns `Empty question. Provide non-empty text.`
- `system` (when provided) is prepended as `f"{system}\n\n{question}"` before
  passing to `client.send()`.

### Known v1 limitations (deferred to v0.2.0)

- **WS-leak race under concurrent first-time callers.** Documented in
  `peers/{claude,chatgpt}.py` `_ensure_session` docstrings. Cosmetic on
  subprocess shutdown; the v0.2.0 fix is per-call WS lifecycle (open in
  `_send_uncounted`, close in `finally`).
- **`/health` does not return 503 on degraded** (T22 still open). The
  mcp-common `register_http_health_route` API lacks a `degraded_status_code`
  parameter; the fix is to wrap or override the route handler. Bodai-wide
  monthly audit will flag this.
- **Coverage gap at 79.48%** vs the 89% gate. Tests for the streaming-done
  detection paths (indicator + content-hash stability branches in
  `peers/{claude,chatgpt}.py`) need explicit unit tests — the current
  fixtures terminate at the success path.
- **`/health` envelope is startup-snapshot, not live.** `extra_components`
  captured once at `startup()`; per-call cycle counters and last-updated
  timestamps don't refresh on `curl /health`. Live aggregation via
  `auth_health_provider` callable is the planned v0.2.0 shape.

### Repo provenance

- Renamed from `cross-llm-mcp` on 2026-09-16 (commit `cafe354`).
- Listed in the Bodai registry at
  `lesleslie/mahavishnu/BODAI_REPO_REGISTRY.md` line 60.
- GitHub remote: `https://github.com/lesleslie/chat-bridge-mcp`.

### Pre-1.0 policy reminder

Per `bodai-pre-1.0-merge-policy.md`, all changes to this repo merge directly
to `main`. No PRs. No `git push` without explicit user approval.
