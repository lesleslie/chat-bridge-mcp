# AGENTS.md

> Repo-local edit rules, layout, and validation entry points for chat-bridge-mcp.

## Layout

```
chat-bridge-mcp/
├── chat_bridge_mcp/
│   ├── __init__.py            # __version__
│   ├── __main__.py            # CLI entry: from chat_bridge_mcp.server import app
│   ├── _tools.py              # @mcp.tool() decorators (6 chat-bridge tools)
│   ├── cdp.py                 # CDPConnection + CDPSession (WebSocket)
│   ├── config.py              # ChatBridgeConfig (pydantic BaseSettings)
│   ├── exceptions.py          # BridgeError + 6 subclasses
│   ├── guardrail.py           # wrap(source_reply, *, source_peer) — strict-isolation framing
│   ├── peers/
│   │   ├── base.py            # DesktopPeerAdapter ABC + HealthFeedState + 4-signal
│   │   ├── claude.py          # ClaudeDesktopAdapter (CDP-driven)
│   │   └── chatgpt.py         # ChatGPTDesktopAdapter (CDP-driven)
│   ├── selectors.py           # load_selectors() + SelectorSet (darwin + windows)
│   └── server.py              # ChatBridgeServer + mcp singleton + /health route
├── settings/
│   └── selectors.yaml         # macOS (darwin) + Windows selectors per peer
├── tests/
│   ├── unit/                  # Fast isolated tests
│   ├── integration/           # Subprocess + fake CDP server
│   └── e2e/                   # Gated behind CHAT_BRIDGE_MCP_E2E=1
├── docs/
│   └── superpowers/
│       ├── specs/             # Design contract
│       └── plans/             # Implementation plan
├── pyproject.toml             # hatchling + [project.urls] + [tool.ruff/mypy/pytest/crackerjack]
├── README.md                  # First-install smoke test, OS support, concurrency caveats
├── CLAUDE.md                  # One-page pointer for Claude Code
├── AGENTS.md                  # This file
├── CHANGELOG.md               # Per-version inventory of changes
└── .gitignore
```

## Build & test

```bash
uv sync --extra dev                       # install + dev deps
uv run pytest                             # 101 passed, 1 skipped (e2e gate)
uv run pytest -m unit                     # fast feedback (78 tests)
uv run pytest tests/integration/ -v       # 22 tests, ~50s
uv run pytest -m e2e                      # gated; needs real Electron fixture
uv run ruff check chat_bridge_mcp/
uv run mypy chat_bridge_mcp/
```

## Edit rules

- **Python 3.14 only.** `requires-python = ">=3.14"`.
- **`from __future__ import annotations`** first line of every source file.
- **Modern syntax**: `X | None`, `list[str]`, `pathlib.Path`. No `Optional[X]`,
  `List[X]`, `os.path`.
- **Function defaults**: `X | None = None`, never `def f(x: int = None)`.
- **No `assert` in production code** (`chat_bridge_mcp/**`). Tests may use asserts.
- **No `Any` in MCP tool inputs.** Tool returns may be `Any` (FastMCP envelope).
- **In `except`**: `logger.exception(...)`, not `logger.error(..., exc_info=True)`.
- **All I/O is async.** No `time.sleep`, `requests`, sync file I/O in async paths.
- **`oneiric.logging`**, not stdlib `logging`, not `print()`.
- **Stable deps use `~=`**, e.g. `mcp-common~=0.25.1`. Early-dev packages
  (`fastmcp>=2`, `pydantic>=2`) keep `>=`.

## Validation gates

| Gate | Command | Status |
|---|---|---|
| Tests | `uv run pytest` | ✅ 101 passed, 1 skipped (e2e gate) |
| Lint | `uv run ruff check chat_bridge_mcp/` | ✅ clean (or 13 trivial style) |
| Types | `uv run mypy chat_bridge_mcp/` | ✅ clean |
| Coverage | `--cov-fail-under=89` | ⚠️ 79.48% — gap in peers/{claude,chatgpt}.py streaming-done branches. v0.2.0 fix. |

## Per-peer collision contract (spec §5.6)

Concurrent calls to the same peer do NOT serialize. Expect prompt-drop data
corruption (both calls return the second call's reply). The integration test
`test_concurrent_calls_pin_drop` pins this contract by name. Don't "fix" it
by adding a lock — the test will fail.

## Knowledge graph entry points

When picking up work, check in this order:

1. `docs/superpowers/specs/2026-09-16-chat-bridge-design.md` — design contract
2. `docs/superpowers/plans/2026-09-16-chat-bridge-impl.md` — implementation history
3. `CHANGELOG.md` — current version inventory
4. `git log --oneline -n 20` — recent commits
5. The 6-agent multi-lens review (see commit history) — known gaps
