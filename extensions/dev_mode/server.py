from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from pathlib import Path
import os
import subprocess


EXTENSIONS_DIR = Path(__file__).resolve().parents[2] / "extensions"
ALLOWED_BASE = EXTENSIONS_DIR.resolve()


def _safe_path(relative: str) -> Path:
    target = (ALLOWED_BASE / relative).resolve()
    if not str(target).startswith(str(ALLOWED_BASE)):
        raise PermissionError("Path traversal detected")
    return target


server = Server("jarvis-dev-mode")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="read_code_file",
            description="Read a source file in the repository.",
            inputSchema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        ),
        Tool(
            name="write_extension_code",
            description="Write extension code. Allowed root: /extensions/ only.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        ),
        Tool(
            name="install_package",
            description="Install a pip package into the active Python environment.",
            inputSchema={"type": "object", "properties": {"package_name": {"type": "string"}}, "required": ["package_name"]},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, object]) -> list[TextContent]:
    if name == "read_code_file":
        rel = str(arguments.get("path", ""))
        target = _safe_path(rel)
        if not target.exists():
            return [TextContent(type="text", text=f"Not found: {rel}")]
        text = target.read_text(encoding="utf-8", errors="ignore")
        return [TextContent(type="text", text=text)]

    if name == "write_extension_code":
        rel = str(arguments.get("path", ""))
        content = str(arguments.get("content", ""))
        target = _safe_path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return [TextContent(type="text", text=f"Wrote: {rel}")]

    if name == "install_package":
        package = str(arguments.get("package_name", "")).strip()
        if not package:
            return [TextContent(type="text", text="Missing package_name")]
        completed = subprocess.run(
            ["python", "-m", "pip", "install", package],
            capture_output=True,
            text=True,
            check=False,
        )
        out = completed.stdout.strip()
        err = completed.stderr.strip()
        return [TextContent(type="text", text=out or err or "Done")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
