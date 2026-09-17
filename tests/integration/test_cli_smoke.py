from __future__ import annotations

import subprocess
import sys


def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "chat_bridge_mcp", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    # Click renders the module name (chat_bridge_mcp) in the Usage line
    # when invoked via `python -m`; the hyphenated program name
    # (chat-bridge-mcp) appears only via the console-script path. Accept
    # either — the assertion's intent is "CLI launches and identifies
    # the program."
    assert "chat-bridge-mcp" in result.stdout or "chat_bridge_mcp" in result.stdout


def test_cli_version_prints():
    result = subprocess.run(
        [sys.executable, "-m", "chat_bridge_mcp", "version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "chat-bridge-mcp 0.1.0" in result.stdout
