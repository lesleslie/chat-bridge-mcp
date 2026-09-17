from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

import yaml

from chat_bridge_mcp.exceptions import SelectorMissingError


REQUIRED_KEYS = ("input_box", "send_button", "response_container")


@dataclass(frozen=True)
class SelectorSet:
    input_box: str
    send_button: str
    response_container: str
    stop_generating_indicator: str | None  # None triggers content-hash fallback (§5.1.c step 5)


def load_selectors(path: Path, *, os_name: str | None = None) -> dict[str, SelectorSet]:
    """Load per-peer CSS selectors from `path` for the current OS.

    Returns a dict keyed by peer name ("claude" | "chatgpt") → SelectorSet.
    Raises SelectorMissingError with a structured context dict if the
    OS block, peer block, or any required key is absent.
    """
    os_name = (os_name or platform.system()).lower()

    if not path.exists():
        raise SelectorMissingError(
            f"selectors file not found at {path}",
            context={"path": str(path)},
        )

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    os_block = data.get(os_name)
    if not isinstance(os_block, dict):
        raise SelectorMissingError(
            f"selectors.yaml missing '{os_name}' block (or it is not a map)",
            context={"path": str(path), "os": os_name, "available_keys": list(data.keys())},
        )

    result: dict[str, SelectorSet] = {}
    for peer in ("claude", "chatgpt"):
        peer_block = os_block.get(peer)
        if not isinstance(peer_block, dict):
            raise SelectorMissingError(
                f"selectors.yaml '{os_name}.{peer}' block missing or not a map",
                context={"path": str(path), "os": os_name, "peer": peer},
            )
        for required in REQUIRED_KEYS:
            if required not in peer_block:
                raise SelectorMissingError(
                    f"selectors.yaml '{os_name}.{peer}.{required}' key missing",
                    context={
                        "path": str(path),
                        "os": os_name,
                        "peer": peer,
                        "missing_key": required,
                    },
                )
        result[peer] = SelectorSet(
            input_box=peer_block["input_box"],
            send_button=peer_block["send_button"],
            response_container=peer_block["response_container"],
            stop_generating_indicator=peer_block.get("stop_generating_indicator"),
        )

    return result