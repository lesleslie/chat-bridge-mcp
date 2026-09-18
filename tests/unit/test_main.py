"""Tests for chat_bridge_mcp.__main__: the entry-point shim."""
from __future__ import annotations

from unittest.mock import patch


def test_main_invokes_app():
    """`python -m chat_bridge_mcp` calls the typer `app` from chat_bridge_mcp.server.

    Covers __main__.py:1-7 (the only 4 statements in the file: import,
    main() definition, app() call, and the `if __name__ == "__main__"` guard).
    """
    from chat_bridge_mcp import __main__

    with patch("chat_bridge_mcp.__main__.app") as mock_app:
        __main__.main()
        mock_app.assert_called_once()
