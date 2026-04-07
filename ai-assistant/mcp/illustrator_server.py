#!/usr/bin/env python3
"""
Illustrator MCP Server (Stub)

A minimal Model Context Protocol server that exposes Adobe Illustrator
automation tools. This is a placeholder that delegates to the
computer_control module for actual mouse/keyboard interactions.

In production, this would be replaced with a full CEP/UXP plugin
or use Illustrator's ExtendScript/JSX automation interface.

Transport: stdio (launched by nanobot)
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))

try:
    from computer_control import ComputerController
except Exception as exc:  # pragma: no cover - runtime import in tool process
    ComputerController = None  # type: ignore[assignment]
    _IMPORT_ERROR = str(exc)
else:
    _IMPORT_ERROR = ""

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "illustrator_mcp.log")],
)
logger = logging.getLogger("illustrator_mcp")

_controller = None


def get_controller():
    global _controller
    if _controller is None:
        if ComputerController is None:
            raise RuntimeError(f"computer_control unavailable: {_IMPORT_ERROR}")
        _controller = ComputerController()
    return _controller


def run_async(coro):
    return asyncio.run(coro)

# ---------------------------------------------------------------------------
# MCP protocol helpers (stdio JSON-RPC)
# ---------------------------------------------------------------------------

def send_response(request_id: int, result: dict) -> None:
    """Send a JSON-RPC response to stdout."""
    msg = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def send_error(request_id: int, code: int, message: str) -> None:
    """Send a JSON-RPC error to stdout."""
    msg = json.dumps({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "illustrator_open",
        "description": "Open Adobe Illustrator",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "illustrator_new_document",
        "description": "Create a new Illustrator document",
        "inputSchema": {
            "type": "object",
            "properties": {
                "width": {"type": "number", "description": "Width in pixels"},
                "height": {"type": "number", "description": "Height in pixels"},
            },
            "required": [],
        },
    },
    {
        "name": "illustrator_add_text",
        "description": "Add text at a position in the document",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "required": ["text", "x", "y"],
        },
    },
    {
        "name": "illustrator_draw_line",
        "description": "Draw a line between two points",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x1": {"type": "number"},
                "y1": {"type": "number"},
                "x2": {"type": "number"},
                "y2": {"type": "number"},
            },
            "required": ["x1", "y1", "x2", "y2"],
        },
    },
    {
        "name": "illustrator_save",
        "description": "Save the current document",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to save to"},
            },
            "required": [],
        },
    },
]


# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------

def handle_request(request: dict) -> None:
    """Handle an incoming JSON-RPC request."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    logger.info("Request: method=%s id=%s", method, req_id)

    if method == "initialize":
        send_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "illustrator-mcp", "version": "0.1.0"},
        })

    elif method == "tools/list":
        send_response(req_id, {"tools": TOOLS})

    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        logger.info("Tool call: %s args=%s", tool_name, tool_args)

        try:
            ctrl = get_controller()

            if tool_name == "illustrator_open":
                opened = run_async(ctrl.open_application("Adobe Illustrator"))
                if opened:
                    send_response(req_id, {"content": [{"type": "text", "text": "Illustrator launched successfully."}]})
                else:
                    send_response(req_id, {"content": [{"type": "text", "text": "Illustrator launch failed. Verify a supported desktop app/binary is installed."}]})

            elif tool_name == "illustrator_new_document":
                w = int(tool_args.get("width", 1920))
                h = int(tool_args.get("height", 1080))
                run_async(ctrl.adobe_new_document(w, h))
                send_response(req_id, {"content": [{"type": "text", "text": f"Created new document: {w}x{h}"}]})

            elif tool_name == "illustrator_add_text":
                text = str(tool_args.get("text", ""))
                x = int(tool_args.get("x", 100))
                y = int(tool_args.get("y", 100))
                run_async(ctrl.adobe_add_text(text, x, y))
                send_response(req_id, {"content": [{"type": "text", "text": f"Added text at ({x}, {y})."}]})

            elif tool_name == "illustrator_draw_line":
                x1 = int(tool_args.get("x1", 100))
                y1 = int(tool_args.get("y1", 100))
                x2 = int(tool_args.get("x2", 400))
                y2 = int(tool_args.get("y2", 200))
                run_async(ctrl.adobe_draw_line((x1, y1), (x2, y2)))
                send_response(req_id, {"content": [{"type": "text", "text": f"Drew line from ({x1}, {y1}) to ({x2}, {y2})."}]})

            elif tool_name == "illustrator_save":
                save_path = tool_args.get("path")
                run_async(ctrl.adobe_save(save_path))
                send_response(req_id, {"content": [{"type": "text", "text": f"Save command sent{f' to {save_path}' if save_path else ''}."}]})

            else:
                send_error(req_id, -32601, f"Unknown tool: {tool_name}")
        except Exception as exc:
            logger.error("Tool call failed: %s", exc)
            send_error(req_id, -32000, str(exc))

    elif method == "notifications/initialized":
        # No response needed for notifications
        pass

    else:
        if req_id is not None:
            send_error(req_id, -32601, f"Method not found: {method}")


def main() -> None:
    """Main loop — read JSON-RPC messages from stdin."""
    logger.info("Illustrator MCP server starting (stdio)")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            handle_request(request)
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON: %s", exc)
        except Exception as exc:
            logger.error("Unhandled error: %s", exc)


if __name__ == "__main__":
    main()
