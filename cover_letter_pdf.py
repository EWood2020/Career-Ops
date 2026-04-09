#!/usr/bin/env python3
"""
Cover letter PDF generator (A4) using ReportLab + built-in Helvetica only.

Primary entrypoint:
  build_cover_letter(filename, role_title, body_paragraphs)
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer


# ── Design tokens (per spec) ────────────────────────────────────────────────────

DARK_NAVY = colors.HexColor("#1a2340")
GREEN = colors.HexColor("#2e7d5e")
MID_GRAY = colors.HexColor("#888888")
TEXT = colors.HexColor("#222222")
RULE = colors.HexColor("#dddddd")

MARGIN = 18 * mm

# Header content (matches your CV/CoverLetter PDFs)
HEADER_NAME = "Enrique Wood Rivero"
HEADER_LINE2 = "Prague, Czech Republic (EU citizen) | enriquewori@gmail.com"
HEADER_LINE3 = "linkedin.com/in/enriquewood"
HEADER_LINE4 = "enriquewood.tech | +34 618 253 083"


def _style_no_hyphenation(ps: ParagraphStyle) -> ParagraphStyle:
    ps.hyphenationLang = ""
    ps.embeddedHyphenation = 0
    return ps


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_cover_letter(filename: str | Path, role_title: str, body_paragraphs: list[str]) -> None:
    """
    Generate a cover letter PDF (A4) matching the CV style.

    Args:
      filename: output PDF path
      role_title: centered role title line (green)
      body_paragraphs: list of paragraph strings (EXCLUDING the greeting)
    """
    out_path = Path(filename)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    base = getSampleStyleSheet()

    s_name = _style_no_hyphenation(ParagraphStyle(
        "CL_HeaderName",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=DARK_NAVY,
        alignment=TA_CENTER,
        spaceAfter=2,
    ))
    s_header = _style_no_hyphenation(ParagraphStyle(
        "CL_HeaderLine",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=MID_GRAY,
        alignment=TA_CENTER,
        spaceAfter=1,
    ))
    s_role = _style_no_hyphenation(ParagraphStyle(
        "CL_RoleTitle",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=GREEN,
        alignment=TA_CENTER,
        spaceBefore=8,
        spaceAfter=8,
    ))
    s_body = _style_no_hyphenation(ParagraphStyle(
        "CL_Body",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=15,
        textColor=TEXT,
        alignment=TA_JUSTIFY,
        spaceAfter=8,
    ))
    s_sig_name = _style_no_hyphenation(ParagraphStyle(
        "CL_SignatureName",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=15,
        textColor=DARK_NAVY,
        spaceAfter=1,
    ))
    s_sig_line = _style_no_hyphenation(ParagraphStyle(
        "CL_SignatureLine",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=MID_GRAY,
        spaceAfter=0,
    ))

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"Cover Letter — {role_title}",
        author=HEADER_NAME,
    )

    rule = HRFlowable(width="100%", thickness=0.5, color=RULE, spaceBefore=6, spaceAfter=6)

    story = []

    # Header (centered)
    story.append(Paragraph(_escape(HEADER_NAME), s_name))
    story.append(Paragraph(_escape(HEADER_LINE2), s_header))
    story.append(Paragraph(_escape(HEADER_LINE3), s_header))
    story.append(Paragraph(_escape(HEADER_LINE4), s_header))
    story.append(rule)

    # Role title (centered, between rules)
    story.append(Paragraph(_escape(role_title), s_role))
    story.append(rule)
    story.append(Spacer(1, 6))

    # Body
    story.append(Paragraph("Dear Hiring Team,", s_body))
    for p in body_paragraphs or []:
        if not (p or "").strip():
            continue
        story.append(Paragraph(_escape(p.strip()), s_body))

    # Signature
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Best regards,", s_body))
    story.append(Paragraph(_escape(HEADER_NAME), s_sig_name))
    story.append(Paragraph(_escape("+34 618 253 083 | enriquewood.tech"), s_sig_line))

    doc.build(story)


def _demo() -> None:
    build_cover_letter(
        "output/CoverLetter_demo.pdf",
        "Adoption & Change Consultant",
        [
            "I'm applying for the Adoption & Change Consultant role because I've spent the last several years solving exactly this problem: making digital transformation stick inside organizations that have real constraints.",
            "My strongest proof point is the structure I've built around cross-functional alignment.",
            "What drew me to this role is the chance to do this at scale and in focused partnership.",
        ],
    )


if __name__ == "__main__":
    _demo()

