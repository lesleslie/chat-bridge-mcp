# Changelog

All notable changes to chat-bridge-mcp are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres
to [Semantic Versioning](https://semver.org/) within Bodai's pre-1.0 convention
(surface additions are minor; wire-up fixes are patch; spec-breaking changes
are major).

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
