from __future__ import annotations

import pytest

from chat_bridge_mcp.config import (
    ChatBridgeConfig,
    DEFAULT_PORT,
    load_config,
)


def test_default_port_constant():
    assert DEFAULT_PORT == 3057


def test_defaults_via_loader():
    cfg = load_config()  # uses Oneiric's load_settings; CHAT_BRIDGE_MCP_* env vars apply
    assert cfg.http_port == DEFAULT_PORT
    assert cfg.http_host == "127.0.0.1"
    assert cfg.cdp_host == "127.0.0.1"
    assert cfg.cdp_claude_port == 9229
    assert cfg.cdp_chatgpt_port == 9230
    assert cfg.streaming_timeout_seconds == 180.0
    assert cfg.polling_interval_seconds == 1.5
    assert cfg.strict_mode_on_start is True
    assert cfg.guardrail_template is None


def test_env_var_overrides(monkeypatch):
    monkeypatch.setenv("CHAT_BRIDGE_MCP_HTTP_PORT", "4057")
    monkeypatch.setenv("CHAT_BRIDGE_MCP_STREAMING_TIMEOUT_SECONDS", "300")
    cfg = load_config()
    assert cfg.http_port == 4057
    assert cfg.streaming_timeout_seconds == 300.0


def test_yaml_overrides_defaults(tmp_path, monkeypatch):
    yaml_path = tmp_path / "chat-bridge-mcp.yaml"
    yaml_path.write_text("http_port: 7777\nstreaming_timeout_seconds: 90\n")
    monkeypatch.setenv("CHAT_BRIDGE_MCP_SETTINGS_FILE", str(yaml_path))
    cfg = load_config()
    assert cfg.http_port == 7777
    assert cfg.streaming_timeout_seconds == 90


def test_selectors_file_is_anchored_on_install_location():
    cfg = load_config()
    expected_suffix = "chat-bridge-mcp/settings/selectors.yaml"
    assert str(cfg.selectors_file).endswith(expected_suffix)


def test_validate_for_start_rejects_short_timeout():
    cfg = load_config(streaming_timeout_seconds=1.0, polling_interval_seconds=2.0)
    with pytest.raises(ValueError, match="polling_interval_seconds .* too long"):
        cfg.validate_for_start()


def test_validate_for_start_allows_defaults():
    load_config().validate_for_start()
