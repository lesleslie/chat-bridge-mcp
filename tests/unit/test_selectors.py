from __future__ import annotations

import pytest

from chat_bridge_mcp.exceptions import SelectorMissingError
from chat_bridge_mcp.selectors import SelectorSet, load_selectors


def test_load_selectors_darwin_returns_two_peers():
    from chat_bridge_mcp.config import DEFAULT_PORT  # noqa: F401  (forces package init)
    # Use the bundled settings file (anchored on install location).
    # Platform.system() returns "Darwin" on macOS; load_selectors's
    # os_name lookup matches the YAML key.
    from chat_bridge_mcp.config import ChatBridgeConfig
    cfg = ChatBridgeConfig()
    result = load_selectors(cfg.selectors_file, os_name="darwin")
    assert set(result.keys()) == {"claude", "chatgpt"}
    for peer, sel in result.items():
        assert isinstance(sel, SelectorSet)
        assert sel.input_box
        assert sel.send_button
        assert sel.response_container
        # stop_generating_indicator is optional (None triggers content-hash fallback)


def test_load_selectors_missing_os_block_raises(tmp_path):
    # File must exist so the file-not-found check passes; the YAML
    # payload intentionally omits the `darwin:` block so load_selectors
    # reaches the OS-block check and raises SelectorMissingError with
    # the "missing '<os>' block" message.
    yaml_file = tmp_path / "selectors.yaml"
    yaml_file.write_text("windows:\n  claude:\n    input_box: 'x'\n    send_button: 'y'\n    response_container: 'z'\n  chatgpt:\n    input_box: 'x'\n    send_button: 'y'\n    response_container: 'z'\n")
    with pytest.raises(SelectorMissingError, match="missing 'darwin' block"):
        load_selectors(yaml_file, os_name="darwin")


def test_load_selectors_missing_required_key_raises(tmp_path):
    yaml = tmp_path / "broken.yaml"
    yaml.write_text("darwin:\n  claude:\n    input_box: 'x'\n")  # missing send_button, response_container
    with pytest.raises(SelectorMissingError, match="missing"):
        load_selectors(yaml, os_name="darwin")


def test_load_selectors_raises_when_file_missing(tmp_path):
    """Selectors file path does not exist -> SelectorMissingError ("not found").
    Covers selectors.py:33.
    """
    missing_path = tmp_path / "does-not-exist.yaml"
    with pytest.raises(SelectorMissingError, match="selectors file not found"):
        load_selectors(missing_path, os_name="darwin")


def test_load_selectors_raises_when_peer_block_missing_or_not_map(tmp_path):
    """OS block exists but the per-peer block is missing/not a mapping ->
    SelectorMissingError. Covers selectors.py:52.
    """
    yaml = tmp_path / "selectors.yaml"
    # darwin.claude exists, but darwin.chatgpt is a list (not a mapping).
    yaml.write_text(
        "darwin:\n"
        "  claude:\n"
        "    input_box: 'x'\n    send_button: 'y'\n    response_container: 'z'\n"
        "  chatgpt: [not, a, map]\n"
    )
    with pytest.raises(SelectorMissingError, match=r"darwin\.chatgpt"):
        load_selectors(yaml, os_name="darwin")
