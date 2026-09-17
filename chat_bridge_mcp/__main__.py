from __future__ import annotations

import typer

from chat_bridge_mcp import __version__

app = typer.Typer(
    name="chat-bridge-mcp",
    help="Bridge MCP for Claude Desktop and ChatGPT Desktop via Chrome DevTools Protocol.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _root() -> None:
    """Bridge MCP for Claude Desktop and ChatGPT Desktop via Chrome DevTools Protocol."""


@app.command()
def version() -> None:
    """Print the bridge version and exit."""
    typer.echo(f"chat-bridge-mcp {__version__}")


def main() -> None:
    """Entry point. Subsequent tasks (Task 11) wire up start/stop/health/etc."""
    app()


if __name__ == "__main__":
    main()
