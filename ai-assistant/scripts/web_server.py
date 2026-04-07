#!/usr/bin/env python3
"""
Bid Processing Assistant - Web Chat Server

Full-featured fallback web server that provides:
  - Chat with local LLM (Ollama) including system prompt and conversation history
  - Intent detection to route messages to agents (web search, bid processing, computer control)
  - Approval flow for sensitive actions (computer control, email)
  - Session management (per-browser-tab conversation memory)

Usage:
    python3 web_server.py <install_dir> <llm_model> [port]
"""

import asyncio
import http.server
import json
import logging
import os
import re
import secrets
import socketserver
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
INSTALL_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/ai-assistant")
LLM_MODEL = sys.argv[2] if len(sys.argv) > 2 else "llama3.2:3b"
try:
    PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 3000
except ValueError:
    PORT = 3000

sys.path.insert(0, os.path.join(INSTALL_DIR, "agent"))

LOG_DIR = Path(INSTALL_DIR) / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "web_server.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("web_server")

# Load config
CONFIG_PATH = Path(INSTALL_DIR) / "config" / "nanobot.json"
try:
    with open(CONFIG_PATH) as f:
        CONFIG = json.load(f)
except Exception:
    CONFIG = {}

SYSTEM_PROMPT = CONFIG.get("system_prompt", "You are a helpful construction bid processing assistant.")
APPROVAL_ACTIONS = CONFIG.get("security", {}).get("require_approval_for", ["send_email", "delete_file", "web_browse_unknown"])

# ---------------------------------------------------------------------------
# Agent lazy loaders
# ---------------------------------------------------------------------------
_web_controller = None
_computer_controller = None
_bid_agent = None


def get_web_controller():
    global _web_controller
    if _web_controller is None:
        try:
            from web_access import WebAccessController
            _web_controller = WebAccessController()
            logger.info("WebAccessController initialized")
        except Exception as e:
            logger.error("Failed to init WebAccessController: %s", e)
    return _web_controller


def get_computer_controller():
    global _computer_controller
    if _computer_controller is None:
        try:
            from computer_control import ComputerController
            _computer_controller = ComputerController()
            logger.info("ComputerController initialized")
        except Exception as e:
            logger.error("Failed to init ComputerController: %s", e)
    return _computer_controller


def get_bid_agent():
    global _bid_agent
    if _bid_agent is None:
        try:
            from bid_agent import BidAgent
            _bid_agent = BidAgent(model=LLM_MODEL)
            logger.info("BidAgent initialized")
        except Exception as e:
            logger.error("Failed to init BidAgent: %s", e)
    return _bid_agent


# ---------------------------------------------------------------------------
# Session and approval state
# ---------------------------------------------------------------------------
sessions: Dict[str, List[Dict[str, str]]] = {}  # session_id -> message history
pending_actions: Dict[str, Dict[str, Any]] = {}  # action_id -> action details

MAX_HISTORY = 20  # Max messages per session


def get_history(session_id: str) -> List[Dict[str, str]]:
    if session_id not in sessions:
        sessions[session_id] = []
    return sessions[session_id]


def add_to_history(session_id: str, role: str, content: str):
    history = get_history(session_id)
    history.append({"role": role, "content": content})
    # Trim old messages but keep system context
    if len(history) > MAX_HISTORY:
        sessions[session_id] = history[-MAX_HISTORY:]


# ---------------------------------------------------------------------------
# Async runner helper (run async code from sync handler)
# ---------------------------------------------------------------------------
_loop = None
_loop_thread = None


def get_event_loop():
    global _loop, _loop_thread
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
        _loop_thread.start()
    return _loop


def run_async(coro, timeout: int = 120):
    """Run an async coroutine from sync code, return the result."""
    loop = get_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------
INTENT_PATTERNS = {
    "web_search": [
        r"(?:search|look up|find|google|lookup|browse|web search)\s+(?:for\s+|the web for\s+|online for\s+)?(.+)",
        r"(?:can you |please )?(?:search|look up|find|google)\s+(?:for\s+|the web for\s+)?(.+)",
        r"what (?:is|are) the (?:price|cost)s? (?:of|for)\s+(.+)",
        r"find prices? (?:for|of)\s+(.+)",
        r"(?:search|look) (?:on |)(?:the )?(?:web|internet|online)\s+(?:for\s+)?(.+)",
    ],
    "material_price": [
        r"(?:price|cost|how much)\s+(?:of|for|does|is)\s+(.+?)(?:\s+cost)?$",
        r"(?:lookup|look up) (?:material )?price\s+(?:for|of)\s+(.+)",
        r"how much (?:does|do|is|are)\s+(.+?)(?:\s+cost)?$",
        r"what(?:'s| is| are) the (?:price|cost)\s+(?:of|for)\s+(.+)",
    ],
    "process_bid": [
        r"(?:process|analyze|analyse|parse|read|extract)\s+(?:the\s+)?(?:bid|pdf|document)\s+(.+)",
        r"(?:process|analyze|analyse|parse|read)\s+(.+\.pdf)",
    ],
    "take_screenshot": [
        r"(?:take|capture|grab)\s+(?:a\s+)?screenshot",
        r"screenshot",
    ],
    "click": [
        r"click\s+(?:at\s+)?(?:\(?\s*(\d+)\s*,\s*(\d+)\s*\)?|on\s+(.+))",
    ],
    "type_text": [
        r"type\s+[\"'](.+?)[\"']",
        r"type\s+(.+)",
    ],
    "open_app": [
        r"open\s+(?:app(?:lication)?\s+)?(?:the\s+)?(.+)",
        r"launch\s+(.+)",
        r"start\s+(?:up\s+)?(.+)",
    ],
    "compose_email": [
        r"(?:compose|send|write|draft)\s+(?:an?\s+)?email",
        r"email\s+(?:to|about)\s+(.+)",
    ],
    "search_bids": [
        r"(?:search|find|look for)\s+(?:bid\s+)?opportunities?\s*(?:for\s+)?(.+)?",
        r"(?:find|search)\s+(?:construction\s+)?bids?\s*(?:for\s+|in\s+)?(.+)?",
    ],
    "capabilities": [
        r"(?:what can you do|what are your (?:capabilities|features|tools|abilities))",
        r"(?:do you have|have you got)\s+(?:web|internet|online)\s+access",
        r"can you (?:browse|access|use)\s+(?:the\s+)?(?:web|internet|online)",
        r"(?:do you have|have you got)\s+access to\s+(?:the\s+)?(?:web|internet)",
        r"what tools\s+(?:do you have|are available)",
        r"(?:list|show|tell me)\s+(?:your\s+)?(?:capabilities|features|tools|abilities)",
        r"can you (?:search|go)\s+(?:the\s+)?(?:web|internet|online)",
    ],
}

REQUIRES_APPROVAL = {"take_screenshot", "click", "type_text", "open_app", "compose_email"}

TOOL_TIMEOUTS = {
    "web_search": 45,
    "material_price": 45,
    "search_bids": 60,
    "process_bid": 180,
    "take_screenshot": 20,
    "click": 20,
    "type_text": 25,
    "open_app": 45,
    "compose_email": 45,
}


def detect_intent(message: str) -> Optional[Dict[str, Any]]:
    """Detect the user's intent from their message using keyword patterns."""
    msg_lower = message.lower().strip()
    logger.info("Detecting intent for: '%s'", msg_lower[:100])

    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, msg_lower, re.IGNORECASE)
            if match:
                logger.info("Intent matched: %s (pattern: %s)", intent, pattern[:50])
                return {
                    "intent": intent,
                    "match": match,
                    "groups": match.groups(),
                    "original": message,
                }
    logger.info("No intent matched — routing to LLM")
    return None


# ---------------------------------------------------------------------------
# Tool executors
# ---------------------------------------------------------------------------
async def execute_web_search(query: str) -> str:
    web = get_web_controller()
    if not web:
        return "Web search is not available (missing dependencies: aiohttp, beautifulsoup4)."
    try:
        results = await web.search(query, num_results=5)
        if not results:
            return f"No results found for: {query}"
        lines = [f"**Web search results for '{query}':**\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', 'No title')}")
            if r.get("url"):
                lines.append(f"   {r['url']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Web search error: {e}"


async def execute_material_price(material: str) -> str:
    web = get_web_controller()
    if not web:
        return "Price lookup not available (missing dependencies)."
    try:
        price = await web.lookup_material_price(material)
        if price is not None:
            return f"Estimated price for '{material}': ${price:.2f}"
        return f"Could not find a price for '{material}'. Try being more specific (e.g., '4x8 drywall sheet')."
    except Exception as e:
        return f"Price lookup error: {e}"


async def execute_process_bid(filepath: str) -> str:
    agent = get_bid_agent()
    if not agent:
        return "Bid processing agent is not available (missing dependencies: PyPDF2, ollama)."
    path = Path(filepath.strip().strip("'\"")).expanduser()
    if not path.exists():
        return f"File not found: {path}\nMake sure the file path is correct."
    try:
        result = await agent.process(str(path))
        total = result.get("total_quote", 0)
        items = len(result.get("line_items", []))
        return (
            f"Bid processed successfully!\n\n"
            f"  Title: {result.get('bid_title', 'N/A')}\n"
            f"  Client: {result.get('client_name', 'N/A')}\n"
            f"  Line items: {items}\n"
            f"  Material cost: ${result.get('material_cost', 0):.2f}\n"
            f"  Labor: {result.get('labor_hours', 0)} hrs @ ${result.get('labor_rate', 0):.2f}/hr\n"
            f"  Markup ({result.get('markup_percent', 0)}%): ${result.get('markup_amount', 0):.2f}\n"
            f"  Tax ({result.get('tax_percent', 0)}%): ${result.get('tax_amount', 0):.2f}\n"
            f"  TOTAL QUOTE: ${total:.2f}\n\n"
            f"Quote saved to: {result.get('output_path', 'N/A')}"
        )
    except Exception as e:
        return f"Bid processing error: {e}"


async def execute_take_screenshot() -> str:
    ctrl = get_computer_controller()
    if not ctrl:
        return "Computer control is not available (missing pyautogui). Make sure you have a display connected."
    try:
        path = await ctrl.take_screenshot()
        return f"Screenshot saved to: {path}"
    except Exception as e:
        return f"Screenshot error: {e}"


async def execute_click(x: int, y: int) -> str:
    ctrl = get_computer_controller()
    if not ctrl:
        return "Computer control is not available (missing pyautogui)."
    try:
        await ctrl.click(x, y)
        return f"Clicked at ({x}, {y})"
    except Exception as e:
        return f"Click error: {e}"


async def execute_type_text(text: str) -> str:
    ctrl = get_computer_controller()
    if not ctrl:
        return "Computer control is not available (missing pyautogui)."
    try:
        await ctrl.type_text(text)
        return f"Typed: {text}"
    except Exception as e:
        return f"Type error: {e}"


async def execute_open_app(app_name: str) -> str:
    ctrl = get_computer_controller()
    if not ctrl:
        return "Computer control is not available (missing pyautogui)."
    try:
        success = await ctrl.open_application(app_name)
        if success:
            return f"Opened application: {app_name}"
        return f"Failed to open: {app_name}"
    except Exception as e:
        return f"Open app error: {e}"


async def execute_compose_email(to: str, subject: str, body: str) -> str:
    web = get_web_controller()
    if not web:
        return "Email composition not available (missing dependencies)."
    try:
        result = await web.compose_email(to, subject, body)
        return (
            f"Email draft ready:\n"
            f"  To: {result['to']}\n"
            f"  Subject: {subject}\n"
            f"  Provider: {result['provider']}\n"
            f"  URL: {result['compose_url']}\n\n"
            f"Open the URL above to review and send."
        )
    except Exception as e:
        return f"Email error: {e}"


async def execute_search_bids(keywords: str, location: str = "") -> str:
    web = get_web_controller()
    if not web:
        return "Bid search not available (missing dependencies)."
    try:
        results = await web.search_bid_opportunities(keywords, location)
        if not results:
            return f"No bid opportunities found for: {keywords}"
        lines = [f"**Bid opportunities for '{keywords}':**\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', 'No title')}")
            if r.get("url"):
                lines.append(f"   {r['url']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Bid search error: {e}"


# ---------------------------------------------------------------------------
# Message handler (main logic)
# ---------------------------------------------------------------------------
def handle_chat(session_id: str, message: str) -> Dict[str, Any]:
    """Process a chat message: detect intent, run tools or LLM, return response."""
    add_to_history(session_id, "user", message)

    # Check for intent
    intent_info = detect_intent(message)

    if intent_info:
        intent = intent_info["intent"]
        groups = intent_info["groups"]
        logger.info("Detected intent: %s (groups=%s)", intent, groups)

        # Actions that need approval
        if intent in REQUIRES_APPROVAL:
            action_id = str(uuid.uuid4())[:8]
            action_desc = _describe_action(intent, groups, message)
            pending_actions[action_id] = {
                "intent": intent,
                "groups": groups,
                "message": message,
                "session_id": session_id,
                "created": time.time(),
            }
            response_text = (
                f"This action requires your approval:\n\n"
                f"  {action_desc}\n\n"
                f"Click 'Approve' to proceed or 'Cancel' to skip."
            )
            add_to_history(session_id, "assistant", response_text)
            return {
                "response": response_text,
                "approval_required": True,
                "action_id": action_id,
                "action_description": action_desc,
            }

        # Actions that can run immediately
        try:
            result = _execute_immediate(intent, groups, message)
            add_to_history(session_id, "assistant", result)
            return {"response": result}
        except Exception as e:
            error_msg = f"Tool error: {e}"
            add_to_history(session_id, "assistant", error_msg)
            return {"response": error_msg}

    # No tool intent — regular LLM chat
    try:
        import ollama as _ollama

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(get_history(session_id))

        resp = _ollama.chat(
            model=LLM_MODEL,
            messages=messages,
            options={"temperature": 0.7, "num_predict": 4096},
        )
        answer = resp["message"]["content"]
        add_to_history(session_id, "assistant", answer)
        return {"response": answer}
    except Exception as e:
        error_msg = f"LLM error: {e}"
        add_to_history(session_id, "assistant", error_msg)
        return {"response": error_msg}


def _describe_action(intent: str, groups: tuple, message: str) -> str:
    """Create a human-readable description of a pending action."""
    if intent == "take_screenshot":
        return "Take a screenshot of your screen"
    elif intent == "click":
        if groups[0] and groups[1]:
            return f"Click at coordinates ({groups[0]}, {groups[1]})"
        return f"Click on: {groups[2] if len(groups) > 2 and groups[2] else 'target'}"
    elif intent == "type_text":
        text = next((g for g in groups if g), message)
        return f"Type text: '{text[:50]}'"
    elif intent == "open_app":
        app = next((g for g in groups if g), "application")
        return f"Open application: {app}"
    elif intent == "compose_email":
        return "Compose and prepare an email (you'll review before sending)"
    return f"Execute: {intent}"


def _execute_immediate(intent: str, groups: tuple, message: str) -> str:
    """Execute a tool that doesn't need approval. Returns result text."""
    if intent == "web_search":
        query = next((g for g in groups if g), message)
        return run_async(execute_web_search(query), timeout=TOOL_TIMEOUTS["web_search"])
    elif intent == "material_price":
        material = next((g for g in groups if g), message)
        return run_async(execute_material_price(material), timeout=TOOL_TIMEOUTS["material_price"])
    elif intent == "process_bid":
        filepath = next((g for g in groups if g), "")
        return run_async(execute_process_bid(filepath), timeout=TOOL_TIMEOUTS["process_bid"])
    elif intent == "search_bids":
        keywords = next((g for g in groups if g), "construction")
        return run_async(execute_search_bids(keywords), timeout=TOOL_TIMEOUTS["search_bids"])
    elif intent == "capabilities":
        return (
            "Yes! Here's what I can do:\n\n"
            "**Web Search** — Search the internet via DuckDuckGo\n"
            "  Try: 'search for drywall prices' or 'look up HVAC contractors'\n\n"
            "**Material Price Lookup** — Find construction material costs\n"
            "  Try: 'how much does a 4x8 drywall sheet cost'\n\n"
            "**Bid Processing** — Analyze bid PDFs and generate quotes\n"
            "  Try: 'process bid /path/to/file.pdf'\n\n"
            "**Bid Opportunity Search** — Find open bid opportunities\n"
            "  Try: 'find bid opportunities for commercial HVAC'\n\n"
            "**Computer Control** *(requires approval)* — Screenshots, clicks, typing, open apps\n"
            "  Try: 'take a screenshot' or 'open the calculator'\n\n"
            "**Email Composition** *(requires approval)* — Draft and prepare emails\n"
            "  Try: 'compose email to vendor about pricing'\n\n"
            "Just type naturally and I'll use the right tool!"
        )
    return "Unknown action."


def handle_approve(action_id: str) -> Dict[str, Any]:
    """Execute a previously queued action that required approval."""
    action = pending_actions.pop(action_id, None)
    if not action:
        return {"response": "Action not found or already expired.", "approved": False}

    # Expire actions older than 5 minutes
    if time.time() - action["created"] > 300:
        return {"response": "Action expired. Please try again.", "approved": False}

    intent = action["intent"]
    groups = action["groups"]
    message = action["message"]
    session_id = action["session_id"]

    try:
        if intent == "take_screenshot":
            result = run_async(execute_take_screenshot(), timeout=TOOL_TIMEOUTS["take_screenshot"])
        elif intent == "click":
            x = int(groups[0]) if groups[0] else 0
            y = int(groups[1]) if groups[1] else 0
            result = run_async(execute_click(x, y), timeout=TOOL_TIMEOUTS["click"])
        elif intent == "type_text":
            text = next((g for g in groups if g), "")
            result = run_async(execute_type_text(text), timeout=TOOL_TIMEOUTS["type_text"])
        elif intent == "open_app":
            app = next((g for g in groups if g), "")
            result = run_async(execute_open_app(app), timeout=TOOL_TIMEOUTS["open_app"])
        elif intent == "compose_email":
            result = run_async(execute_compose_email(
                to="recipient@example.com",
                subject="From Bid Assistant",
                body=message,
            ), timeout=TOOL_TIMEOUTS["compose_email"])
        else:
            result = "Unknown action type."

        add_to_history(session_id, "assistant", f"[Approved] {result}")
        return {"response": result, "approved": True}
    except Exception as e:
        error_msg = f"Action failed: {e}"
        add_to_history(session_id, "assistant", error_msg)
        return {"response": error_msg, "approved": False}


# ---------------------------------------------------------------------------
# HTML Frontend
# ---------------------------------------------------------------------------
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bid Processing Assistant</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }
.header { background: #16213e; padding: 16px 24px; border-bottom: 1px solid #0f3460; display: flex; align-items: center; justify-content: space-between; }
.header-left h1 { font-size: 18px; color: #e94560; }
.header-left p { font-size: 12px; color: #888; margin-top: 4px; }
.tools-badge { display: flex; gap: 6px; flex-wrap: wrap; }
.tools-badge span { font-size: 10px; padding: 3px 8px; border-radius: 10px; background: #0f3460; color: #7ea8d9; }
.chat { flex: 1; overflow-y: auto; padding: 24px; }
.msg { margin-bottom: 16px; max-width: 85%; }
.msg.user { margin-left: auto; }
.msg .bubble { padding: 12px 16px; border-radius: 12px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-wrap: break-word; }
.msg.user .bubble { background: #0f3460; }
.msg.bot .bubble { background: #16213e; border: 1px solid #0f3460; }
.msg.system .bubble { background: #2a1a3e; border: 1px solid #4a2070; font-size: 13px; }
.approval-buttons { display: flex; gap: 8px; margin-top: 8px; }
.approval-buttons button { padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; font-weight: 500; }
.btn-approve { background: #27ae60; color: white; }
.btn-approve:hover { background: #219a52; }
.btn-cancel { background: #555; color: #ccc; }
.btn-cancel:hover { background: #666; }
.input-area { padding: 16px 24px; background: #16213e; border-top: 1px solid #0f3460; display: flex; gap: 12px; }
.input-area input { flex: 1; background: #1a1a2e; border: 1px solid #0f3460; color: #e0e0e0; padding: 12px 16px; border-radius: 8px; font-size: 14px; outline: none; }
.input-area input:focus { border-color: #e94560; }
.input-area button { background: #e94560; color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-size: 14px; }
.input-area button:hover { background: #c73650; }
.input-area button:disabled { background: #555; cursor: not-allowed; }
.status { font-size: 11px; color: #4a4a6a; text-align: center; padding: 8px; display: flex; justify-content: center; gap: 16px; }
.status .dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 4px; }
.dot-green { background: #27ae60; }
.dot-yellow { background: #f39c12; }
.thinking { color: #888; font-style: italic; }
.tool-tag { display: inline-block; font-size: 10px; padding: 2px 6px; border-radius: 4px; background: #4a2070; color: #c89aff; margin-bottom: 4px; }
</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <h1>Bid Processing Assistant</h1>
    <p>Local LLM &bull; Web Search &bull; Computer Control &bull; Bid Processing</p>
  </div>
  <div class="tools-badge">
    <span>Web Search</span>
    <span>Bid Analysis</span>
    <span>Computer Control</span>
    <span>Email</span>
  </div>
</div>
<div class="chat" id="chat">
  <div class="msg bot"><div class="bubble">Ready! Here's what I can do:

&bull; <b>Chat</b> &mdash; Ask me anything about construction bids
&bull; <b>Search</b> &mdash; "search for drywall prices" or "find bid opportunities for commercial HVAC"
&bull; <b>Process bids</b> &mdash; "process bid ~/Downloads/bid.pdf"
&bull; <b>Computer control</b> &mdash; "take a screenshot", "open Adobe Photoshop" (requires your approval)
&bull; <b>Email</b> &mdash; "compose email" (requires your approval)

Type a message to get started.</div></div>
</div>
<div class="input-area">
  <input type="text" id="input" placeholder="Type a message, paste a file path, or ask me to search..." autofocus>
  <button id="sendBtn" onclick="send()">Send</button>
</div>
<div class="status">
  <span><span class="dot dot-green"></span>Ollama (localhost:11434)</span>
  <span><span class="dot dot-green"></span>AgentGuard active</span>
  <span id="sessionInfo"></span>
</div>
<script>
const chat = document.getElementById('chat');
const input = document.getElementById('input');
const sendBtn = document.getElementById('sendBtn');

// Session ID for conversation continuity
const SESSION_ID = 'sess_' + Math.random().toString(36).substring(2, 10);
document.getElementById('sessionInfo').textContent = 'Session: ' + SESSION_ID.slice(5);

input.addEventListener('keydown', e => { if (e.key === 'Enter' && !sendBtn.disabled) send(); });

async function send() {
  const msg = input.value.trim();
  if (!msg) return;
  addMsg(msg, 'user');
  input.value = '';
  sendBtn.disabled = true;
  const thinkingId = showThinking();

  try {
    const r = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Session-ID': SESSION_ID},
      body: JSON.stringify({message: msg})
    });
        const data = await parseJsonResponse(r);
    removeThinking(thinkingId);

    if (data.approval_required) {
      addApprovalMsg(data.response, data.action_id, data.action_description);
        } else if (data.error) {
            addMsg('Server error: ' + data.error, 'bot');
    } else {
      addMsg(data.response || 'No response.', 'bot');
    }
  } catch(e) {
    removeThinking(thinkingId);
    addMsg('Connection error: ' + e.message, 'bot');
  }
  sendBtn.disabled = false;
  input.focus();
}

async function approve(actionId, btnContainer) {
  btnContainer.innerHTML = '<span class="thinking">Executing...</span>';
  try {
    const r = await fetch('/approve', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Session-ID': SESSION_ID},
      body: JSON.stringify({action_id: actionId})
    });
        const data = await parseJsonResponse(r);
        if (data.error) {
            addMsg('Action failed: ' + data.error, 'bot');
            return;
        }
        addMsg(data.response || 'Action completed.', 'bot');
  } catch(e) {
    addMsg('Action failed: ' + e.message, 'bot');
  }
}

async function parseJsonResponse(response) {
    const text = await response.text();
    if (!text) {
        return { error: `Empty response from server (${response.status})` };
    }
    try {
        return JSON.parse(text);
    } catch (_) {
        return { error: `Non-JSON server response (${response.status}): ${text.slice(0, 200)}` };
    }
}

function cancel(actionId, btnContainer) {
  btnContainer.innerHTML = '<span style="color:#888;">Cancelled.</span>';
}

function formatMsg(text) {
  let s = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
  s = s.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener" style="color:#7ea8d9;">$1</a>');
  s = s.replace(/\n/g, '<br>');
  return s;
}
function addMsg(text, role) {
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  const b = document.createElement('div');
  b.className = 'bubble';
  b.innerHTML = formatMsg(text);
  d.appendChild(b);
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
}

function addApprovalMsg(text, actionId, desc) {
  const d = document.createElement('div');
  d.className = 'msg system';
  const b = document.createElement('div');
  b.className = 'bubble';

  const tag = document.createElement('span');
  tag.className = 'tool-tag';
  tag.textContent = 'Approval Required';
  b.appendChild(tag);

  const t = document.createElement('div');
  t.textContent = text;
  t.style.marginTop = '6px';
  b.appendChild(t);

  const btns = document.createElement('div');
  btns.className = 'approval-buttons';

  const approveBtn = document.createElement('button');
  approveBtn.className = 'btn-approve';
  approveBtn.textContent = 'Approve';
  approveBtn.onclick = () => approve(actionId, btns);

  const cancelBtn = document.createElement('button');
  cancelBtn.className = 'btn-cancel';
  cancelBtn.textContent = 'Cancel';
  cancelBtn.onclick = () => cancel(actionId, btns);

  btns.appendChild(approveBtn);
  btns.appendChild(cancelBtn);
  b.appendChild(btns);

  d.appendChild(b);
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
}

function showThinking() {
  const id = 'think_' + Date.now();
  const d = document.createElement('div');
  d.className = 'msg bot';
  d.id = id;
  d.innerHTML = '<div class="bubble thinking">Thinking...</div>';
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return id;
}

function removeThinking(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------
class ChatHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self._json_response(200, {"status": "ok", "model": LLM_MODEL})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(HTML.encode())

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 65536:
                self._json_response(413, {"error": "Request too large"})
                return

            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                self._json_response(400, {"error": "Invalid JSON body"})
                return

            session_id = self.headers.get("X-Session-ID", "default")

            if self.path == "/chat":
                message = str(body.get("message", ""))[:4096]
                if not message:
                    self._json_response(400, {"error": "Empty message"})
                    return
                result = handle_chat(session_id, message)
                self._json_response(200, result)

            elif self.path == "/approve":
                action_id = str(body.get("action_id", ""))
                if not action_id:
                    self._json_response(400, {"error": "Missing action_id"})
                    return
                result = handle_approve(action_id)
                self._json_response(200, result)

            else:
                self._json_response(404, {"error": "Not found"})
        except Exception as exc:
            logger.exception("Unhandled POST error: %s", exc)
            self._json_response(500, {"error": "Internal server error"})

    def _json_response(self, status: int, data: dict):
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        except BrokenPipeError:
            logger.warning("Client disconnected before response was written")

    def log_message(self, fmt, *args):
        logger.debug(fmt, *args)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    # Cleanup stale pending actions periodically
    def cleanup_stale_actions():
        while True:
            time.sleep(60)
            now = time.time()
            expired = [k for k, v in pending_actions.items() if now - v["created"] > 300]
            for k in expired:
                pending_actions.pop(k, None)

    cleanup_thread = threading.Thread(target=cleanup_stale_actions, daemon=True)
    cleanup_thread.start()

    logger.info("Starting web server on port %d with model %s", PORT, LLM_MODEL)
    with ReusableTCPServer(("0.0.0.0", PORT), ChatHandler) as httpd:
        print(f"Bid Processing Assistant running on http://0.0.0.0:{PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down web server")
