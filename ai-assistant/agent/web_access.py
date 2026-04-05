#!/usr/bin/env python3
"""
Web Access Module - Browser Automation and Web Interaction

Provides web browsing, search, content extraction, and email sending
capabilities for the bid processing assistant.

Uses aiohttp for HTTP requests and BeautifulSoup for HTML parsing.
All web actions are logged and subject to AgentGuard network policy.

Usage:
    from web_access import WebAccessController
    web = WebAccessController()
    results = await web.search("construction material prices")
    content = await web.fetch_page("https://example.com")
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse

try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore[assignment]

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment,misc]

LOG_DIR = Path(os.environ.get("AI_ASSISTANT_LOG_DIR", Path.home() / "ai-assistant" / "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "web_access.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("web_access")

# ---------------------------------------------------------------------------
# Allowed domains (enforced in addition to AgentGuard network policy)
# ---------------------------------------------------------------------------
ALLOWED_DOMAINS: set = {
    "localhost",
    "127.0.0.1",
    # Search engines
    "www.google.com",
    "google.com",
    "html.duckduckgo.com",
    "duckduckgo.com",
    # Email providers
    "mail.google.com",
    "outlook.live.com",
    "outlook.office365.com",
    # Construction / bid sites
    "www.rsmeans.com",
    "www.homedepot.com",
    "www.lowes.com",
    "www.grainger.com",
    # GitHub / tools
    "github.com",
    "raw.githubusercontent.com",
    "registry.npmjs.org",
    "pypi.org",
}

# Allow overriding via env var (comma-separated)
_extra = os.environ.get("ALLOWED_DOMAINS", "")
if _extra:
    ALLOWED_DOMAINS.update(d.strip() for d in _extra.split(",") if d.strip())

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = int(os.environ.get("WEB_TIMEOUT", "30"))


class WebAccessController:
    """Web browsing, search, and email automation with security restrictions."""

    def __init__(self) -> None:
        """Initialise the web access controller, verifying dependencies."""
        if aiohttp is None:
            raise RuntimeError("aiohttp is not installed. Run: pip install aiohttp")
        if BeautifulSoup is None:
            raise RuntimeError("beautifulsoup4 is not installed. Run: pip install beautifulsoup4")
        logger.info("WebAccessController initialised")

    # ------------------------------------------------------------------
    # Domain validation
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_url(url: str) -> str:
        """Ensure a URL targets an allowed domain. Raises ValueError otherwise."""
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if hostname not in ALLOWED_DOMAINS:
            raise ValueError(
                f"Domain '{hostname}' is not in the allowed list. "
                "Add it to ALLOWED_DOMAINS or the ALLOWED_DOMAINS env var."
            )
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
        return url

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    async def _get(self, url: str, headers: Optional[Dict[str, str]] = None) -> str:
        """Perform a validated GET request and return the response body."""
        url = self._validate_url(url)
        _headers = {"User-Agent": USER_AGENT}
        if headers:
            _headers.update(headers)

        logger.info("GET %s", url)
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=_headers, ssl=True) as resp:
                resp.raise_for_status()
                body = await resp.text()
                logger.info("GET %s -> %d (%d bytes)", url, resp.status, len(body))
                return body

    async def _post(self, url: str, data: Optional[Dict[str, Any]] = None, json_body: Optional[Dict[str, Any]] = None) -> str:
        """Perform a validated POST request."""
        url = self._validate_url(url)
        headers = {"User-Agent": USER_AGENT}

        logger.info("POST %s", url)
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, data=data, json=json_body, ssl=True) as resp:
                resp.raise_for_status()
                body = await resp.text()
                logger.info("POST %s -> %d", url, resp.status)
                return body

    # ------------------------------------------------------------------
    # Page fetching & content extraction
    # ------------------------------------------------------------------
    async def fetch_page(self, url: str) -> Dict[str, Any]:
        """
        Fetch a web page and extract its main text content.

        Returns:
            Dict with keys: url, title, text, links
        """
        html = await self._get(url)
        soup = BeautifulSoup(html, "html.parser")

        # Remove script and style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        text = soup.get_text(separator="\n", strip=True)

        # Extract links
        links = []
        for a_tag in soup.find_all("a", href=True)[:50]:
            href = a_tag["href"]
            link_text = a_tag.get_text(strip=True)
            if href.startswith("http"):
                links.append({"text": link_text, "url": href})

        return {
            "url": url,
            "title": title,
            "text": text[:5000],  # Truncate for LLM context
            "links": links,
        }

    # ------------------------------------------------------------------
    # Web search
    # ------------------------------------------------------------------
    async def search(self, query: str, num_results: int = 5) -> List[Dict[str, str]]:
        """
        Search the web using DuckDuckGo (no API key required).

        Args:
            query: Search query string.
            num_results: Maximum number of results to return.

        Returns:
            List of dicts with keys: title, url, snippet
        """
        logger.info("search query='%s' num_results=%d", query, num_results)

        # DuckDuckGo HTML search (no API key needed)
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        html = await self._get(search_url)
        soup = BeautifulSoup(html, "html.parser")

        results: List[Dict[str, str]] = []
        for result_div in soup.find_all("div", class_="result")[:num_results]:
            title_tag = result_div.find("a", class_="result__a")
            snippet_tag = result_div.find("a", class_="result__snippet")
            if title_tag:
                results.append(
                    {
                        "title": title_tag.get_text(strip=True),
                        "url": title_tag.get("href", ""),
                        "snippet": snippet_tag.get_text(strip=True) if snippet_tag else "",
                    }
                )

        logger.info("Search returned %d results", len(results))
        return results

    # ------------------------------------------------------------------
    # Material price lookup
    # ------------------------------------------------------------------
    async def lookup_material_price(self, material: str) -> Optional[float]:
        """
        Search for current material pricing online.

        Args:
            material: Material description (e.g. "4x8 drywall sheet").

        Returns:
            Estimated price in USD, or None if not found.
        """
        logger.info("lookup_material_price material='%s'", material)

        results = await self.search(f"{material} price USD 2024")
        for result in results:
            snippet = result.get("snippet", "")
            # Look for price patterns
            price_match = re.search(r"\$(\d+(?:\.\d{2})?)", snippet)
            if price_match:
                price = float(price_match.group(1))
                if 0.01 < price < 100_000:  # Sanity check
                    logger.info("Found price for '%s': $%.2f", material, price)
                    return price

        logger.warning("Could not find price for '%s'", material)
        return None

    # ------------------------------------------------------------------
    # Email (via web interface)
    # ------------------------------------------------------------------
    async def compose_email(
        self,
        to: str,
        subject: str,
        body: str,
        provider: str = "gmail",
    ) -> Dict[str, str]:
        """
        Prepare an email composition URL for web-based email.

        This does NOT send the email directly — it generates the mailto/compose
        URL that the computer control module can open in the browser. Actual
        sending requires user approval via AgentGuard.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Email body text.
            provider: Email provider ('gmail' or 'outlook').

        Returns:
            Dict with the compose URL and a human-readable summary.
        """
        logger.info("compose_email to=%s subject='%s' provider=%s", to, subject, provider)

        # Validate email format
        if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", to):
            raise ValueError(f"Invalid email address: {to}")

        encoded_subject = quote_plus(subject)
        encoded_body = quote_plus(body)

        if provider == "gmail":
            compose_url = (
                f"https://mail.google.com/mail/?view=cm"
                f"&to={to}&su={encoded_subject}&body={encoded_body}"
            )
        elif provider == "outlook":
            compose_url = (
                f"https://outlook.live.com/mail/0/deeplink/compose"
                f"?to={to}&subject={encoded_subject}&body={encoded_body}"
            )
        else:
            # Fallback to mailto
            compose_url = f"mailto:{to}?subject={encoded_subject}&body={encoded_body}"

        return {
            "compose_url": compose_url,
            "to": to,
            "subject": subject,
            "provider": provider,
            "status": "ready_to_send",
            "note": "Open this URL to review and send. Requires user approval.",
        }

    # ------------------------------------------------------------------
    # Bid-specific web actions
    # ------------------------------------------------------------------
    async def search_bid_opportunities(self, keywords: str, location: str = "") -> List[Dict[str, str]]:
        """Search for construction bid opportunities online.

        Args:
            keywords: Search terms (e.g. 'commercial renovation').
            location: Geographic filter (e.g. 'Texas').

        Returns:
            List of search result dicts with title, url, snippet.
        """
        query = f"construction bid opportunity {keywords}"
        if location:
            query += f" {location}"
        return await self.search(query, num_results=10)

    async def download_file(self, url: str, save_dir: Optional[Path] = None) -> Path:
        """
        Download a file from an allowed URL.

        Args:
            url: URL of the file to download.
            save_dir: Directory to save the file (defaults to ~/Documents/Bids/).

        Returns:
            Path to the downloaded file.
        """
        url = self._validate_url(url)
        if save_dir is None:
            save_dir = Path.home() / "Documents" / "Bids"
        save_dir.mkdir(parents=True, exist_ok=True)

        parsed = urlparse(url)
        filename = Path(parsed.path).name or "download"
        filepath = save_dir / filename

        logger.info("Downloading %s -> %s", url, filepath)
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"User-Agent": USER_AGENT}, ssl=True) as resp:
                resp.raise_for_status()
                content = await resp.read()
                with open(filepath, "wb") as fh:
                    fh.write(content)

        logger.info("Downloaded %d bytes to %s", len(content), filepath)
        return filepath
