"""chat_bridge_mcp.tools — profiles submodule for tool gating.

Tools themselves are bound at module load via
``chat_bridge_mcp._tools.register_tools`` using ``@mcp.tool()``
decorators against the module-level ``chat_bridge_mcp.server.mcp``
singleton; the ``profiles`` submodule exposes the
``apply_chat_bridge_tool_profile`` function used in ``server.py`` to
honor the ``CHAT_BRIDGE_TOOL_PROFILE`` env var.
"""

from __future__ import annotations
