from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml

# Single source of truth for the bridge port. Catalog grep target.
DEFAULT_PORT: int = 3057


class ChatBridgeConfig(BaseSettings):
    """Configuration for chat-bridge-mcp.

    Extends `pydantic_settings.BaseSettings` directly (not
    `OneiricMCPConfig`) because OneiricMCPConfig is `BaseModel`-based
    and silently ignores `SettingsConfigDict` overrides. BaseSettings
    gives us real env-var precedence: CHAT_BRIDGE_MCP_HTTP_PORT etc.
    apply, then the YAML defaults at settings/chat-bridge-mcp.yaml
    (or whichever path CHAT_BRIDGE_MCP_SETTINGS_FILE points at),
    then the explicit-constructor kwargs (highest precedence).
    """

    http_port: int = DEFAULT_PORT
    http_host: str = "127.0.0.1"

    cdp_host: str = "127.0.0.1"
    cdp_claude_port: int = 9229
    cdp_chatgpt_port: int = 9230

    streaming_timeout_seconds: float = 180.0
    polling_interval_seconds: float = 1.5

    # Anchored on the package install location so wheel installs work
    # without env-var overrides. NOT cwd-relative.
    selectors_file: Path = Path(__file__).resolve().parent.parent / "settings" / "selectors.yaml"

    guardrail_template: str | None = None
    strict_mode_on_start: bool = True

    model_config = SettingsConfigDict(
        env_prefix="CHAT_BRIDGE_MCP_",
        env_file=".env",
        extra="allow",
    )

    def validate_for_start(self) -> None:
        """Fail fast on misconfiguration that guarantees a streaming_timeout.

        At least two polls are required for streaming-done detection.
        A tighter budget would always raise StreamingTimeoutError.
        """
        if self.polling_interval_seconds * 2 > self.streaming_timeout_seconds:
            raise ValueError(
                f"polling_interval_seconds ({self.polling_interval_seconds}) "
                f"too long for streaming_timeout_seconds "
                f"({self.streaming_timeout_seconds}); need at least two polls "
                f"to detect stream end."
            )


def load_config(**overrides: object) -> ChatBridgeConfig:
    """Build ChatBridgeConfig with the standard Pydantic precedence:
    explicit kwargs > env vars > YAML defaults > field defaults.

    Honors `CHAT_BRIDGE_MCP_SETTINGS_FILE` env var (a YAML path); when
    set, fields in that file override field defaults but are themselves
    overridden by env vars and explicit kwargs.
    """
    yaml_overrides: dict[str, object] = {}
    yaml_path = os.environ.get("CHAT_BRIDGE_MCP_SETTINGS_FILE")
    if yaml_path:
        path = Path(yaml_path)
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                yaml_overrides = yaml.safe_load(f) or {}
    merged = yaml_overrides | overrides
    return ChatBridgeConfig.model_validate(merged)
