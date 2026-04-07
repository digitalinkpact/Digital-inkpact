#!/usr/bin/env python3
"""
Computer Control Module - Mouse, Keyboard, and Screen Automation

Provides cross-platform mouse/keyboard control and screenshot capture
for automating desktop applications (Adobe Photoshop, Illustrator, etc.).

Uses pyautogui for input simulation and Pillow for screenshot handling.
All actions are logged for audit via AgentGuard.

Usage:
    from computer_control import ComputerController
    ctrl = ComputerController()
    await ctrl.click(500, 300)
    await ctrl.type_text("Hello World")
    screenshot = await ctrl.take_screenshot()
"""

import asyncio
import logging
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

try:
    import pyautogui

    pyautogui.FAILSAFE = True  # Move mouse to corner to abort
    pyautogui.PAUSE = 0.1  # Small pause between actions
except ImportError:
    pyautogui = None  # type: ignore[assignment]

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment,misc]

LOG_DIR = Path(os.environ.get("AI_ASSISTANT_LOG_DIR", Path(__file__).resolve().parent.parent / "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "computer_control.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("computer_control")

SCREENSHOT_DIR = Path(os.environ.get("SCREENSHOT_DIR", Path(__file__).resolve().parent.parent / "screenshots"))
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


class ComputerController:
    """Cross-platform mouse/keyboard controller with safety guardrails."""

    def __init__(self, safety_delay: float = 0.5) -> None:
        """
        Args:
            safety_delay: Minimum seconds between actions (prevents runaway automation).
        """
        if pyautogui is None:
            raise RuntimeError("pyautogui is not installed. Run: pip install pyautogui")
        self.safety_delay = safety_delay
        self._last_action_time = 0.0
        self.system = platform.system()  # "Darwin", "Windows", "Linux"
        if self.system == "Linux" and not os.environ.get("DISPLAY"):
            raise RuntimeError(
                "DISPLAY is not set. Desktop automation requires an active graphical session. "
                "Start an X session (or Xvfb) and set DISPLAY before using computer control."
            )
        logger.info("ComputerController initialised  platform=%s", self.system)

    def _throttle(self) -> None:
        """Enforce minimum delay between actions."""
        elapsed = time.monotonic() - self._last_action_time
        if elapsed < self.safety_delay:
            time.sleep(self.safety_delay - elapsed)
        self._last_action_time = time.monotonic()

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------
    async def move_to(self, x: int, y: int, duration: float = 0.3) -> None:
        """Move the mouse cursor to (x, y) over *duration* seconds."""
        self._throttle()
        logger.info("move_to x=%d y=%d duration=%.1f", x, y, duration)
        pyautogui.moveTo(x, y, duration=duration)

    async def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> None:
        """Click at (x, y). button can be 'left', 'right', or 'middle'."""
        self._throttle()
        logger.info("click x=%d y=%d button=%s clicks=%d", x, y, button, clicks)
        pyautogui.click(x, y, button=button, clicks=clicks)

    async def double_click(self, x: int, y: int) -> None:
        """Double-click at (x, y)."""
        await self.click(x, y, clicks=2)

    async def right_click(self, x: int, y: int) -> None:
        """Right-click at (x, y)."""
        await self.click(x, y, button="right")

    async def drag_to(self, start: Tuple[int, int], end: Tuple[int, int], duration: float = 0.5) -> None:
        """Click-and-drag from *start* to *end*."""
        self._throttle()
        logger.info("drag_to start=%s end=%s", start, end)
        pyautogui.moveTo(start[0], start[1])
        pyautogui.drag(end[0] - start[0], end[1] - start[1], duration=duration)

    async def scroll(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Scroll the mouse wheel. Positive = up, negative = down."""
        self._throttle()
        logger.info("scroll clicks=%d x=%s y=%s", clicks, x, y)
        pyautogui.scroll(clicks, x=x, y=y)

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------
    async def type_text(self, text: str, interval: float = 0.06) -> None:
        """Type text character by character with *interval* delay."""
        self._throttle()
        logger.info("type_text len=%d", len(text))
        pyautogui.typewrite(text, interval=interval)

    async def hotkey(self, *keys: str) -> None:
        """Press a keyboard shortcut (e.g., hotkey('ctrl', 's'))."""
        self._throttle()
        logger.info("hotkey keys=%s", keys)
        pyautogui.hotkey(*keys)

    async def press(self, key: str) -> None:
        """Press and release a single key."""
        self._throttle()
        logger.info("press key=%s", key)
        pyautogui.press(key)

    async def key_down(self, key: str) -> None:
        """Hold a key down (remember to release it)."""
        self._throttle()
        logger.info("key_down key=%s", key)
        pyautogui.keyDown(key)

    async def key_up(self, key: str) -> None:
        """Release a held key."""
        logger.info("key_up key=%s", key)
        pyautogui.keyUp(key)

    # ------------------------------------------------------------------
    # Screenshots
    # ------------------------------------------------------------------
    async def take_screenshot(self, region: Optional[Tuple[int, int, int, int]] = None) -> Path:
        """
        Capture a screenshot and save to the screenshots directory.

        Args:
            region: Optional (left, top, width, height) to capture a sub-region.

        Returns:
            Path to the saved screenshot PNG.
        """
        logger.info("take_screenshot region=%s", region)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = SCREENSHOT_DIR / f"screenshot_{timestamp}.png"

        try:
            screenshot = pyautogui.screenshot(region=region)
            screenshot.save(str(filename))
            logger.info("Screenshot saved: %s", filename)
            return filename
        except Exception as exc:
            display = os.environ.get("DISPLAY", "<unset>")
            logger.error("Screenshot failed (DISPLAY=%s): %s", display, exc)
            raise RuntimeError(f"Screenshot failed. Verify desktop session and DISPLAY (current: {display}).") from exc

    async def locate_on_screen(self, image_path: str, confidence: float = 0.8) -> Optional[Tuple[int, int]]:
        """
        Find an image on the screen and return its centre coordinates.

        Args:
            image_path: Path to a reference PNG image to search for.
            confidence: Match confidence threshold (0.0 - 1.0).

        Returns:
            (x, y) centre of the found image, or None if not found.
        """
        logger.info("locate_on_screen image=%s confidence=%.2f", image_path, confidence)
        try:
            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            if location:
                centre = pyautogui.center(location)
                logger.info("Found at (%d, %d)", centre.x, centre.y)
                return (centre.x, centre.y)
        except Exception as exc:
            logger.warning("locate_on_screen failed: %s", exc)
        return None

    # ------------------------------------------------------------------
    # Application launching
    # ------------------------------------------------------------------
    async def open_application(self, app_name: str) -> bool:
        """
        Open a desktop application by name.

        Args:
            app_name: Application name (e.g. "Adobe Photoshop", "Adobe Illustrator").

        Returns:
            True if the application was launched successfully.
        """
        logger.info("open_application app=%s platform=%s", app_name, self.system)

        try:
            if self.system == "Darwin":
                subprocess.Popen(["open", "-a", app_name])
            elif self.system == "Windows":
                os.startfile(app_name)  # type: ignore[attr-defined]
            else:
                # Linux: resolve a launchable binary from common aliases.
                normalized = app_name.lower().strip()
                aliases = {
                    "adobe photoshop": ["photoshop", "adobe-photoshop", "gimp"],
                    "photoshop": ["photoshop", "adobe-photoshop", "gimp"],
                    "adobe illustrator": ["illustrator", "adobe-illustrator", "inkscape"],
                    "illustrator": ["illustrator", "adobe-illustrator", "inkscape"],
                }
                candidates = aliases.get(normalized, [normalized.replace(" ", "-")])
                binary = next((cmd for cmd in candidates if shutil.which(cmd)), None)
                if not binary:
                    logger.error("No launchable binary found for '%s' (candidates=%s)", app_name, candidates)
                    return False
                subprocess.Popen([binary])

            await asyncio.sleep(5)  # Give desktop apps time to initialise
            logger.info("Application launched: %s", app_name)
            return True
        except Exception as exc:
            logger.error("Failed to open %s: %s", app_name, exc)
            return False

    # ------------------------------------------------------------------
    # Adobe-specific helpers
    # ------------------------------------------------------------------
    async def adobe_new_document(self, width: int = 1920, height: int = 1080) -> None:
        """Create a new document in the active Adobe application."""
        logger.info("adobe_new_document %dx%d", width, height)
        if self.system == "Darwin":
            await self.hotkey("command", "n")
        else:
            await self.hotkey("ctrl", "n")
        await asyncio.sleep(1)
        # Type dimensions if dialog is open
        await self.type_text(str(width))
        await self.press("tab")
        await self.type_text(str(height))
        await self.press("enter")
        await asyncio.sleep(1)

    async def adobe_save(self, filepath: Optional[str] = None) -> None:
        """Save the current document (Ctrl/Cmd+S)."""
        logger.info("adobe_save filepath=%s", filepath)
        if self.system == "Darwin":
            await self.hotkey("command", "s")
        else:
            await self.hotkey("ctrl", "s")

        if filepath:
            await asyncio.sleep(1)
            await self.type_text(filepath)
            await self.press("enter")

    async def adobe_add_text(self, text: str, x: int, y: int) -> None:
        """Add text at a position in Adobe Photoshop/Illustrator."""
        logger.info("adobe_add_text text='%s' at (%d, %d)", text[:30], x, y)
        # Select text tool (T key)
        await self.press("t")
        await asyncio.sleep(0.3)
        await self.click(x, y)
        await asyncio.sleep(0.3)
        await self.type_text(text)

    async def adobe_draw_line(self, start: Tuple[int, int], end: Tuple[int, int]) -> None:
        """Draw a line in Adobe from start to end coordinates."""
        logger.info("adobe_draw_line %s -> %s", start, end)
        # Select line tool
        await self.press("u")
        await asyncio.sleep(0.3)
        await self.drag_to(start, end)

    async def adobe_add_callout(
        self, text: str, arrow_start: Tuple[int, int], arrow_end: Tuple[int, int]
    ) -> None:
        """Draw an arrow and add text for a callout annotation."""
        logger.info("adobe_add_callout text='%s'", text[:30])
        await self.adobe_draw_line(arrow_start, arrow_end)
        await asyncio.sleep(0.3)
        await self.adobe_add_text(text, arrow_end[0] + 10, arrow_end[1] - 20)
