from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chat_bridge_mcp.config import ChatBridgeConfig


# The keys that MUST exist per peer per OS. The v1.0.0 contract.
REQUIRED_KEYS = ("input_box", "send_button", "response_container")
PEERS = ("claude", "chatgpt")
# Platform key fix: YAML keys are platform.system().lower() values,
# not marketing names. macOS is "darwin" (kernel name); Windows is
# "windows"; Linux is out of scope for v1.0.0.
OSS = ("darwin", "windows")


def _load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def test_selectors_yaml_exists_and_is_a_mapping():
    cfg = ChatBridgeConfig()
    assert cfg.selectors_file.exists(), (
        f"selectors.yaml missing at {cfg.selectors_file}"
    )
    data = _load_yaml(cfg.selectors_file)
    assert isinstance(data, dict)


@pytest.mark.parametrize("os_name", OSS)
@pytest.mark.parametrize("peer", PEERS)
def test_selectors_yaml_has_required_keys_per_peer_per_os(os_name, peer):
    cfg = ChatBridgeConfig()
    data = _load_yaml(cfg.selectors_file)
    os_block = data.get(os_name)
    assert isinstance(os_block, dict), (
        f"selectors.yaml missing '{os_name}' block"
    )
    peer_block = os_block.get(peer)
    assert isinstance(peer_block, dict), (
        f"selectors.yaml missing '{os_name}.{peer}' block"
    )
    for required in REQUIRED_KEYS:
        assert required in peer_block, (
            f"selectors.yaml missing '{os_name}.{peer}.{required}' key"
        )


def test_stop_generating_indicator_is_optional():
    """Operator can deliberately set the indicator to null (forcing the
    content-hash fallback). The schema must permit it."""
    cfg = ChatBridgeConfig()
    data = _load_yaml(cfg.selectors_file)
    for os_name in OSS:
        for peer in PEERS:
            peer_block = data[os_name][peer]
            # The key may be present (string) or absent (None at load time);
            # it must NOT be present with a non-string non-null value.
            if "stop_generating_indicator" in peer_block:
                value = peer_block["stop_generating_indicator"]
                assert value is None or isinstance(value, str), (
                    f"stop_generating_indicator at {os_name}.{peer} must "
                    f"be a string or null, got {type(value).__name__}"
                )