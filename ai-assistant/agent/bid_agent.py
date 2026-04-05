#!/usr/bin/env python3
"""
Bid Processing Agent - Autonomous AI Assistant

This agent runs 100% locally using Ollama and MCP tools.
It processes bid packages (PDF), extracts structured data,
generates professional quotes with line items and markup,
and can optionally create drawings via Adobe automation.

Usage:
    python bid_agent.py <path_to_bid.pdf>
    python bid_agent.py <path_to_bid.pdf> --model llama3.2:3b
"""

import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import PyPDF2
except ImportError:
    sys.stderr.write("Missing dependency: pip install PyPDF2\n")
    sys.exit(1)

try:
    import ollama
except ImportError:
    sys.stderr.write("Missing dependency: pip install ollama\n")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = Path(os.environ.get("AI_ASSISTANT_LOG_DIR", Path.home() / "ai-assistant" / "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "bid_agent.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("bid_agent")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "mistral:7b")
WORKSPACE_DIR = Path(os.environ.get("BID_WORKSPACE", Path.home() / "Documents" / "Bids"))
MAX_PDF_TEXT_CHARS = 8000  # Truncate to fit in LLM context
MARKUP_PERCENT = float(os.environ.get("MARKUP_PERCENT", "25"))
TAX_PERCENT = float(os.environ.get("TAX_PERCENT", "8.5"))
DEFAULT_LABOR_RATE = float(os.environ.get("DEFAULT_LABOR_RATE", "75"))


class BidAgent:
    """Main agent for processing bid packages and generating quotes."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        self.workspace = WORKSPACE_DIR
        self.workspace.mkdir(parents=True, exist_ok=True)
        logger.info("BidAgent initialised  model=%s  workspace=%s", model, self.workspace)

    # ------------------------------------------------------------------
    # LLM interaction
    # ------------------------------------------------------------------
    async def think(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Send a prompt to the local Ollama LLM and return the response text."""
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = ollama.chat(
                model=self.model,
                messages=messages,
                options={"temperature": 0.3, "num_predict": 4096},
            )
            return response["message"]["content"]
        except Exception as exc:
            logger.error("LLM query failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # PDF parsing
    # ------------------------------------------------------------------
    async def parse_bid_pdf(self, pdf_path: Path) -> Dict[str, Any]:
        """Extract structured data from a bid-package PDF using the LLM."""
        logger.info("Parsing bid PDF: %s", pdf_path)

        text = self._extract_pdf_text(pdf_path)
        if not text.strip():
            raise ValueError(f"No text could be extracted from {pdf_path}")

        extraction_prompt = f"""
Analyze this bid document and extract key information.

DOCUMENT TEXT:
{text[:MAX_PDF_TEXT_CHARS]}

Return ONLY valid JSON with this exact structure:
{{
    "bid_number": "string or null",
    "bid_title": "string or null",
    "client_name": "string or null",
    "due_date": "YYYY-MM-DD or null",
    "line_items": [
        {{"description": "string", "quantity": number, "unit": "string"}}
    ],
    "labor_hours": number,
    "labor_rate": number,
    "special_requirements": ["string"],
    "contact_info": "string or null"
}}

If information is missing, use null or empty arrays. Be precise with numbers.
"""
        response = await self.think(extraction_prompt)
        data = self._parse_json_response(response)
        logger.info("Extracted %d line items from bid", len(data.get("line_items", [])))
        return data

    @staticmethod
    def _extract_pdf_text(pdf_path: Path) -> str:
        """Read all pages from a PDF and return concatenated text."""
        text_parts: List[str] = []
        with open(pdf_path, "rb") as fh:
            reader = PyPDF2.PdfReader(fh)
            for page_num, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                text_parts.append(f"\n--- Page {page_num + 1} ---\n{page_text}")
        return "".join(text_parts)

    @staticmethod
    def _parse_json_response(response: str) -> Dict[str, Any]:
        """Attempt to parse JSON from an LLM response, with fallback regex extraction."""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            logger.error("Failed to parse JSON from response: %s", response[:500])
            raise

    # ------------------------------------------------------------------
    # Quote generation
    # ------------------------------------------------------------------
    async def generate_quote(self, bid_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a professional quote from extracted bid data."""
        logger.info("Generating quote")

        material_cost = 0.0
        line_items: List[Dict[str, Any]] = []

        for item in bid_data.get("line_items", []):
            unit_price = await self._estimate_unit_price(item["description"])
            quantity = float(item.get("quantity", 0))
            total = quantity * unit_price
            material_cost += total
            line_items.append(
                {
                    "description": item["description"],
                    "quantity": quantity,
                    "unit": item.get("unit", "each"),
                    "unit_price": round(unit_price, 2),
                    "total": round(total, 2),
                }
            )

        labor_hours = float(bid_data.get("labor_hours", 0))
        labor_rate = float(bid_data.get("labor_rate", 0) or DEFAULT_LABOR_RATE)
        labor_cost = labor_hours * labor_rate

        subtotal = material_cost + labor_cost
        markup = subtotal * (MARKUP_PERCENT / 100)
        taxable = subtotal + markup
        tax = taxable * (TAX_PERCENT / 100)
        total_quote = taxable + tax

        quote: Dict[str, Any] = {
            "bid_number": bid_data.get("bid_number"),
            "bid_title": bid_data.get("bid_title"),
            "client_name": bid_data.get("client_name"),
            "generated_date": datetime.now().isoformat(),
            "due_date": bid_data.get("due_date"),
            "line_items": line_items,
            "material_cost": round(material_cost, 2),
            "labor_hours": labor_hours,
            "labor_rate": labor_rate,
            "labor_cost": round(labor_cost, 2),
            "subtotal": round(subtotal, 2),
            "markup_percent": MARKUP_PERCENT,
            "markup_amount": round(markup, 2),
            "tax_percent": TAX_PERCENT,
            "tax_amount": round(tax, 2),
            "total_quote": round(total_quote, 2),
            "special_requirements": bid_data.get("special_requirements", []),
            "contact_info": bid_data.get("contact_info"),
        }

        logger.info("Quote total: $%,.2f", quote["total_quote"])
        return quote

    async def _estimate_unit_price(self, description: str) -> float:
        """Estimate a unit price for a line item based on keyword matching."""
        desc = description.lower()

        price_map: Dict[str, float] = {
            "drywall": 14.50,
            "sheetrock": 14.50,
            "paint": 28.00,
            "gallon": 28.00,
            "flooring": 6.50,
            "carpet": 6.50,
            "tile": 5.00,
            "hardwood": 12.00,
            "baseboard": 2.00,
            "trim": 2.00,
            "lumber": 4.50,
            "stud": 4.50,
            "insulation": 1.20,
            "electrical": 3.50,
            "plumbing": 8.00,
            "light": 25.00,
            "fixture": 35.00,
            "concrete": 7.50,
            "rebar": 1.80,
            "roofing": 4.00,
            "shingle": 1.50,
            "window": 250.00,
            "door": 180.00,
            "hvac": 150.00,
            "duct": 12.00,
            "pipe": 6.00,
            "wire": 0.80,
            "conduit": 3.00,
            "switch": 5.00,
            "outlet": 4.00,
            "panel": 18.00,
            "siding": 5.50,
            "gutter": 6.00,
        }

        for keyword, price in price_map.items():
            if keyword in desc:
                return price

        # Fallback: ask the LLM for an estimate
        try:
            resp = await self.think(
                f"Estimate the unit price in USD for this construction material: '{description}'. "
                "Reply with ONLY a number (no dollar sign, no text)."
            )
            return float(re.search(r"[\d.]+", resp).group())  # type: ignore[union-attr]
        except Exception:
            return 10.00  # safe default

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    async def save_quote(self, quote: Dict[str, Any], output_path: Optional[Path] = None) -> Path:
        """Persist the quote as JSON and a human-readable Markdown file."""
        if output_path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.workspace / f"quote_{ts}.json"

        # JSON
        with open(output_path, "w") as fh:
            json.dump(quote, fh, indent=2)
        logger.info("Quote JSON saved to %s", output_path)

        # Markdown
        md_path = output_path.with_suffix(".md")
        lines: List[str] = [
            f"# Quote for {quote.get('client_name') or 'Client'}",
            "",
            f"**Bid Number:** {quote.get('bid_number') or 'N/A'}",
            f"**Bid Title:** {quote.get('bid_title') or 'N/A'}",
            f"**Date Generated:** {quote.get('generated_date')}",
            f"**Due Date:** {quote.get('due_date') or 'N/A'}",
            "",
            "## Line Items",
            "",
            "| # | Description | Qty | Unit | Unit Price | Total |",
            "|---|-------------|-----|------|------------|-------|",
        ]
        for idx, item in enumerate(quote.get("line_items", []), start=1):
            lines.append(
                f"| {idx} | {item['description']} | {item['quantity']} | {item['unit']} "
                f"| ${item['unit_price']:,.2f} | ${item['total']:,.2f} |"
            )

        lines += [
            "",
            "## Summary",
            "",
            f"| Item | Amount |",
            f"|------|--------|",
            f"| Material Cost | ${quote['material_cost']:,.2f} |",
            f"| Labor ({quote['labor_hours']} hrs @ ${quote['labor_rate']:,.2f}/hr) | ${quote['labor_cost']:,.2f} |",
            f"| **Subtotal** | **${quote['subtotal']:,.2f}** |",
            f"| Markup ({quote['markup_percent']}%) | ${quote['markup_amount']:,.2f} |",
            f"| Tax ({quote['tax_percent']}%) | ${quote['tax_amount']:,.2f} |",
            f"| **Total Quote** | **${quote['total_quote']:,.2f}** |",
            "",
        ]

        if quote.get("special_requirements"):
            lines.append("## Special Requirements")
            lines.append("")
            for req in quote["special_requirements"]:
                lines.append(f"- {req}")
            lines.append("")

        with open(md_path, "w") as fh:
            fh.write("\n".join(lines))
        logger.info("Quote Markdown saved to %s", md_path)

        return output_path

    # ------------------------------------------------------------------
    # Main workflow
    # ------------------------------------------------------------------
    async def process(self, bid_path: str) -> Dict[str, Any]:
        """Complete bid processing workflow: parse -> quote -> save."""
        logger.info("Starting bid processing for %s", bid_path)

        bid_file = Path(bid_path)
        if not bid_file.exists():
            raise FileNotFoundError(f"Bid file not found: {bid_path}")
        if not bid_file.suffix.lower() == ".pdf":
            raise ValueError(f"Expected a PDF file, got: {bid_file.suffix}")

        logger.info("Reading bid package: %s", bid_file.name)
        bid_data = await self.parse_bid_pdf(bid_file)

        logger.info("Generating quote...")
        quote = await self.generate_quote(bid_data)

        output_path = await self.save_quote(quote)

        logger.info("Processing complete!")
        logger.info("Quote saved: %s", output_path)
        logger.info("Total: $%,.2f", quote['total_quote'])
        logger.info("Line items: %d", len(quote['line_items']))

        return quote


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
async def main() -> None:
    """Command-line entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Process a bid package and generate a quote.")
    parser.add_argument("bid_path", help="Path to the bid PDF file")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model to use (default: %(default)s)")
    args = parser.parse_args()

    agent = BidAgent(model=args.model)
    try:
        await agent.process(args.bid_path)
    except Exception as exc:
        logger.error("Processing failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
