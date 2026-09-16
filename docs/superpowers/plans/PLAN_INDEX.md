---
status: active
role: canonical
date: 2026-09-16
last_reviewed: 2026-09-16
superseded_by: null
topic: cross-llm-mcp
---

# Plan Index

**Date:** 2026-09-16
**Last reviewed:** 2026-09-16
**Purpose:** Navigation map for cross-llm-mcp planning documents. Edit by hand until a regenerator exists.

## Status Legend

- `active` — approved and in current use; being executed or applied as policy.
- `complete` — delivered; verification or follow-up may still be open.
- `shipped` — delivered and verified in production; closed.
- `superseded` — replaced by a newer document.
- `draft` — in preparation; not yet approved.

## Plans

| Plan | Date | Status | Role | Spec | Notes |
|---|---|---|---|---|---|
| [2026-09-16-cross-llm-mcp-impl.md](./2026-09-16-cross-llm-mcp-impl.md) | 2026-09-16 | active | implementation | [spec](../specs/2026-09-16-cross-llm-mcp-design.md) | 16 tasks; bridges Claude Desktop ↔ ChatGPT Desktop on port 3057 via CDP |

## Specs

| Spec | Date | Status | Topic |
|---|---|---|---|
| [../specs/2026-09-16-cross-llm-mcp-design.md](../specs/2026-09-16-cross-llm-mcp-design.md) | 2026-09-16 | complete | cross-llm-mcp design |

## Review Entry Points

- Use this file as the first stop before reviewing plan work.
- Source plan for cross-llm-mcp is the 2026-09-16 spec; the implementation plan argues from it.

## Maintenance Rules

- Add new active plans to this index as they are approved.
- When a plan is superseded, leave a pointer in the old file and update its `superseded_by` field.
- Keep status labels aligned with code reality.
