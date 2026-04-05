#!/usr/bin/env python3
"""
Sample Bid PDF Generator

Creates a realistic sample bid PDF for testing the bid processing agent.
Requires: pip install reportlab  (or falls back to a text-based PDF via PyPDF2)

Usage: python generate_sample_bid.py
"""

import os
import sys
from pathlib import Path

SAMPLES_DIR = Path(__file__).parent
OUTPUT_PATH = SAMPLES_DIR / "sample_bid_package.pdf"


def generate_with_reportlab() -> None:
    """Generate a professional-looking sample bid PDF using reportlab."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors

    doc = SimpleDocTemplate(str(OUTPUT_PATH), pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # Header
    story.append(Paragraph("BID PACKAGE", styles["Title"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Project: Riverside Office Renovation", styles["Heading2"]))
    story.append(Paragraph("Bid Number: BID-2026-0042", styles["Normal"]))
    story.append(Paragraph("Client: Riverside Development Corp.", styles["Normal"]))
    story.append(Paragraph("Due Date: 2026-05-15", styles["Normal"]))
    story.append(Paragraph("Contact: John Smith, jsmith@riverside-dev.example.com", styles["Normal"]))
    story.append(Spacer(1, 24))

    # Scope of work
    story.append(Paragraph("SCOPE OF WORK", styles["Heading2"]))
    story.append(Paragraph(
        "Complete interior renovation of the 3rd floor office space at 450 Riverside Drive. "
        "Work includes demolition of existing partitions, new drywall installation, flooring, "
        "electrical upgrades, HVAC modifications, painting, and finish carpentry.",
        styles["Normal"]
    ))
    story.append(Spacer(1, 18))

    # Line items table
    story.append(Paragraph("MATERIAL SCHEDULE", styles["Heading2"]))
    story.append(Spacer(1, 6))

    data = [
        ["Item", "Description", "Quantity", "Unit"],
        ["1", "4x8 Drywall Sheet (5/8\")", "320", "sheets"],
        ["2", "Metal Stud Framing (3-5/8\")", "480", "pieces"],
        ["3", "Insulation R-19 Batts", "2400", "sq ft"],
        ["4", "Commercial Carpet Tile", "3200", "sq ft"],
        ["5", "Interior Latex Paint (5 gal)", "24", "buckets"],
        ["6", "LED Recessed Light Fixture", "48", "each"],
        ["7", "Electrical Outlet (20A)", "64", "each"],
        ["8", "Light Switch (3-way)", "32", "each"],
        ["9", "HVAC Duct (6\" flex)", "200", "linear ft"],
        ["10", "Baseboard Trim (MDF, 4\")", "600", "linear ft"],
        ["11", "Interior Door (hollow core)", "16", "each"],
        ["12", "Door Hardware Set", "16", "each"],
    ]

    table = Table(data, colWidths=[0.5 * inch, 3 * inch, 1 * inch, 1 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#ecf0f1")]),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
    ]))
    story.append(table)
    story.append(Spacer(1, 18))

    # Labor
    story.append(Paragraph("LABOR REQUIREMENTS", styles["Heading2"]))
    story.append(Paragraph("Estimated Labor: 640 hours", styles["Normal"]))
    story.append(Paragraph("Labor Rate: $85.00/hour", styles["Normal"]))
    story.append(Spacer(1, 18))

    # Special requirements
    story.append(Paragraph("SPECIAL REQUIREMENTS", styles["Heading2"]))
    reqs = [
        "All work must comply with local building codes (2024 IBC).",
        "Contractor must maintain active liability insurance ($2M minimum).",
        "Work hours restricted to 7:00 AM - 6:00 PM, Monday through Friday.",
        "Hazardous material abatement (asbestos) may be required on demolition phase.",
        "LEED certification documentation required for all materials.",
        "Prevailing wage rates apply per state labor law.",
    ]
    for req in reqs:
        story.append(Paragraph(f"• {req}", styles["Normal"]))

    story.append(Spacer(1, 24))
    story.append(Paragraph(
        "Please submit your bid by the due date above. Questions may be directed to the contact listed.",
        styles["Normal"]
    ))

    doc.build(story)
    print(f"Sample bid PDF generated: {OUTPUT_PATH}")


def generate_simple() -> None:
    """Generate a simple text-based PDF using PyPDF2 (fallback)."""
    try:
        from PyPDF2 import PdfWriter
        from PyPDF2.generic import NameObject, ArrayObject, NumberObject
    except ImportError:
        print("PyPDF2 not available. Cannot generate sample PDF.")
        sys.exit(1)

    # Create a minimal PDF with text content
    content = """BID PACKAGE
Project: Riverside Office Renovation
Bid Number: BID-2026-0042
Client: Riverside Development Corp.
Due Date: 2026-05-15
Contact: John Smith, jsmith@riverside-dev.example.com

SCOPE OF WORK
Complete interior renovation of the 3rd floor office space.

MATERIAL SCHEDULE
1. 4x8 Drywall Sheet (5/8") - 320 sheets
2. Metal Stud Framing (3-5/8") - 480 pieces
3. Insulation R-19 Batts - 2400 sq ft
4. Commercial Carpet Tile - 3200 sq ft
5. Interior Latex Paint (5 gal) - 24 buckets
6. LED Recessed Light Fixture - 48 each
7. Electrical Outlet (20A) - 64 each
8. Light Switch (3-way) - 32 each
9. HVAC Duct (6" flex) - 200 linear ft
10. Baseboard Trim (MDF, 4") - 600 linear ft
11. Interior Door (hollow core) - 16 each
12. Door Hardware Set - 16 each

LABOR REQUIREMENTS
Estimated Labor: 640 hours
Labor Rate: $85.00/hour

SPECIAL REQUIREMENTS
- All work must comply with local building codes (2024 IBC).
- Contractor must maintain active liability insurance ($2M minimum).
- Work hours restricted to 7:00 AM - 6:00 PM, Monday through Friday.
- Hazardous material abatement (asbestos) may be required.
- LEED certification documentation required for all materials.
- Prevailing wage rates apply per state labor law.
"""

    # Write as a plain text file with .pdf extension for simple testing
    # (The bid agent uses PyPDF2.PdfReader which needs a real PDF)
    # So we create a proper minimal PDF:
    import struct

    pdf_bytes = _build_minimal_pdf(content)
    with open(OUTPUT_PATH, "wb") as f:
        f.write(pdf_bytes)
    print(f"Sample bid PDF (simple) generated: {OUTPUT_PATH}")


def _build_minimal_pdf(text: str) -> bytes:
    """Build a minimal valid PDF containing the given text."""
    lines = text.split("\n")
    # Escape special PDF characters
    escaped = "\\n".join(line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines)

    # Build PDF structure manually
    objects = []
    # Object 1: Catalog
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    # Object 2: Pages
    objects.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
    # Object 3: Page
    objects.append(b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n")
    # Object 4: Content stream
    # Build text operations
    text_ops = "BT\n/F1 10 Tf\n"
    y = 750
    for line in lines:
        safe_line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        text_ops += f"1 0 0 1 50 {y} Tm\n({safe_line}) Tj\n"
        y -= 14
        if y < 50:
            break
    text_ops += "ET\n"
    stream = text_ops.encode("latin-1")
    objects.append(f"4 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream\nendobj\n")
    # Object 5: Font
    objects.append(b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")

    # Build file
    pdf = b"%PDF-1.4\n"
    offsets = []
    for obj in objects:
        offsets.append(len(pdf))
        pdf += obj
    xref_offset = len(pdf)
    pdf += b"xref\n"
    pdf += f"0 {len(objects) + 1}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += f"{off:010d} 00000 n \n".encode()
    pdf += b"trailer\n"
    pdf += f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    pdf += b"startxref\n"
    pdf += f"{xref_offset}\n".encode()
    pdf += b"%%EOF\n"
    return pdf


if __name__ == "__main__":
    try:
        generate_with_reportlab()
    except ImportError:
        print("reportlab not installed, using simple PDF generator...")
        generate_simple()
