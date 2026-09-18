# CLAUDE.md

> One-page pointer for Claude Code working in this repo. For repo layout, build,
> test, and edit rules, see [AGENTS.md](AGENTS.md).

## What this repo is

`chat-bridge-mcp` is a FastMCP server (Bodai MCP, port 3057) that drives
Claude Desktop and ChatGPT Desktop via Chrome DevTools Protocol. It exposes
6 chat-bridge tools (`ask_chatgpt`, `ask_claude`, `forward_chatgpt`,
`forward_claude`, `list_peers`, `get_peer_health`) plus the 4 Bodai baseline
tools (`discover_tools`, `get_liveness`, `get_readiness`, `health_check_all`).

## Pointer

- **Spec**: `docs/superpowers/specs/2026-09-16-chat-bridge-design.md` — read this first
- **Plan**: `docs/superpowers/plans/2026-09-16-chat-bridge-impl.md` — design + spec history
- **Edit rules / layout**: [AGENTS.md](AGENTS.md)
- **Version status**: [CHANGELOG.md](CHANGELOG.md) — currently 0.1.0, no stable release scheduled
- **Wire-up contract**: see `.claude/decisions/wire-up-contract.md` in the
  mahavishnu repo for the Bodai MCP wiring discipline this repo conforms to.

## TL;DR

```bash
uv sync --extra dev        # install
uv run pytest              # 101 passed (1 e2e skipped) — coverage gate at 79.48%, target 89%
uv run ruff check chat_bridge_mcp/
uv run mypy chat_bridge_mcp/
uv run python -m chat_bridge_mcp --help
```

Bridge requires both Claude Desktop and ChatGPT Desktop running with
`--remote-debugging-port` set (9229 and 9230 by default). See
[README.md](README.md) for the first-install smoke test.

## Status

0.1.0 — early development. 6-tool surface complete; several HIGH review
findings still open (T22 /health 503, spec §5.6 WS-leak race documented as
v1 limitation, coverage gate at 79.48% below the 89% target).
