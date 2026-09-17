from __future__ import annotations

from pathlib import Path

import pytest

from chat_bridge_mcp.exceptions import SelectorMissingError
from chat_bridge_mcp.selectors import SelectorSet, load_selectors


def test_load_selectors_macos_returns_two_peers():
    from chat_bridge_mcp.config import DEFAULT_PORT  # noqa: F401  (forces package init)
    # Use the bundled settings file (anchored on install location).
    from chat_bridge_mcp.config import ChatBridgeConfig
    cfg = ChatBridgeConfig()
    result = load_selectors(cfg.selectors_file, os_name="macos")
    assert set(result.keys()) == {"claude", "chatgpt"}
    for peer, sel in result.items():
        assert isinstance(sel, SelectorSet)
        assert sel.input_box
        assert sel.send_button
        assert sel.response_container
        # stop_generating_indicator is optional (None triggers content-hash fallback)


def test_load_selectors_missing_os_block_raises(tmp_path):
    # File must exist so the file-not-found check passes; the YAML
    # payload intentionally omits the `macos:` block so load_selectors
    # reaches the OS-block check and raises SelectorMissingError with
    # the "missing '<os>' block" message.
    yaml_file = tmp_path / "selectors.yaml"
    yaml_file.write_text("windows:\n  claude:\n    input_box: 'x'\n    send_button: 'y'\n    response_container: 'z'\n  chatgpt:\n    input_box: 'x'\n    send_button: 'y'\n    response_container: 'z'\n")
    with pytest.raises(SelectorMissingError, match="missing .* block"):
        load_selectors(yaml_file, os_name="macos")


def test_load_selectors_missing_required_key_raises(tmp_path):
    yaml = tmp_path / "broken.yaml"
    yaml.write_text("macos:\n  claude:\n    input_box: 'x'\n")  # missing send_button, response_container
    with pytest.raises(SelectorMissingError, match="missing"):
        load_selectors(yaml, os_name="macos")