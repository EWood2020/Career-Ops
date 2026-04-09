#!/usr/bin/env python3
"""
Generate a professional CV PDF from cv.md using ReportLab (A4).

Usage:
  python3 generate_cv_pdf.py --input cv.md --output output/CV_Enrique_Wood_Rivero.pdf
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ── Design tokens (per spec) ────────────────────────────────────────────────────

DARK_NAVY = colors.HexColor("#1a2340")
GREEN = colors.HexColor("#2e7d5e")
MID_GRAY = colors.HexColor("#888888")
TEXT = colors.HexColor("#222222")
RULE = colors.HexColor("#dddddd")

MARGIN_LR = 18 * mm
MARGIN_TB = 14 * mm


def _style_no_hyphenation(ps: ParagraphStyle) -> ParagraphStyle:
    # ReportLab supports hyphenation toggles via these attributes.
    ps.hyphenationLang = ""
    ps.embeddedHyphenation = 0
    return ps


def build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()

    header_name = _style_no_hyphenation(ParagraphStyle(
        "HeaderName",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=DARK_NAVY,
        alignment=1,  # centered
        spaceAfter=2,
    ))

    header_line = _style_no_hyphenation(ParagraphStyle(
        "HeaderLine",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=MID_GRAY,
        alignment=1,  # centered
        spaceAfter=1,
    ))

    section_header = _style_no_hyphenation(ParagraphStyle(
        "SectionHeader",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=12,
        textColor=DARK_NAVY,
        alignment=0,
        spaceAfter=0,
        spaceBefore=0,
    ))

    body = _style_no_hyphenation(ParagraphStyle(
        "Body",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8.8,
        leading=13,
        textColor=TEXT,
    ))

    bullet = _style_no_hyphenation(ParagraphStyle(
        "Bullet",
        parent=body,
        leftIndent=8,          # per spec
        bulletIndent=0,
        spaceBefore=0,
        spaceAfter=1,
    ))

    job_title = _style_no_hyphenation(ParagraphStyle(
        "JobTitle",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=12,
        textColor=DARK_NAVY,
        spaceAfter=1,
    ))

    job_meta = _style_no_hyphenation(ParagraphStyle(
        "JobMeta",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=MID_GRAY,
        spaceAfter=3,
    ))

    skill_tags = _style_no_hyphenation(ParagraphStyle(
        "SkillTags",
        parent=base["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8.2,
        leading=11,
        textColor=MID_GRAY,
        leftIndent=8,
        spaceBefore=1,
        spaceAfter=4,
    ))

    skills_label = _style_no_hyphenation(ParagraphStyle(
        "SkillsLabel",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.8,
        leading=13,
        textColor=TEXT,
    ))

    skills_value = _style_no_hyphenation(ParagraphStyle(
        "SkillsValue",
        parent=body,
    ))

    lang_inline = _style_no_hyphenation(ParagraphStyle(
        "LanguagesInline",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8.8,
        leading=13,
        textColor=TEXT,
    ))

    return {
        "header_name": header_name,
        "header_line": header_line,
        "section_header": section_header,
        "body": body,
        "bullet": bullet,
        "job_title": job_title,
        "job_meta": job_meta,
        "skill_tags": skill_tags,
        "skills_label": skills_label,
        "skills_value": skills_value,
        "lang_inline": lang_inline,
    }


def escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def make_section_header(title: str, styles: dict[str, ParagraphStyle]) -> Table:
    para = Paragraph(escape(title.upper()), styles["section_header"])
    t = Table([[para]], colWidths=[None])
    t.setStyle(TableStyle([
        ("LINEBEFORE", (0, 0), (0, 0), 3, GREEN),
        ("LEFTPADDING", (0, 0), (0, 0), 6),
        ("RIGHTPADDING", (0, 0), (0, 0), 0),
        ("TOPPADDING", (0, 0), (0, 0), 1),
        ("BOTTOMPADDING", (0, 0), (0, 0), 3),
    ]))
    return t


def hr() -> HRFlowable:
    return HRFlowable(width="100%", thickness=0.5, color=RULE, spaceBefore=6, spaceAfter=8)


# ── Parsing cv.md (your current markdown conventions) ───────────────────────────

@dataclass
class ExperienceItem:
    title: str
    meta: str
    bullets: list[str]
    skills: str


@dataclass
class CVData:
    name: str
    header_city_email: str
    header_linkedin: str
    header_website_phone: str
    summary: list[str]
    experience: list[ExperienceItem]
    education: list[tuple[str, str]]  # (degree, university|dates)
    certifications: list[str]
    skills: list[tuple[str, str]]     # (label, value)
    languages: list[tuple[str, str]]  # (name, level)


def parse_cv_markdown(md: str) -> CVData:
    lines = [ln.rstrip() for ln in md.splitlines()]

    def get_field(prefix: str) -> str:
        for ln in lines:
            if ln.startswith(prefix):
                # e.g. **Email:** foo
                return ln.split("**", 2)[-1].strip().lstrip(":").strip()
        return ""

    name = ""
    for ln in lines:
        if ln.startswith("# "):
            name = ln[2:].strip()
            break

    city = get_field("**Location:**")
    email = get_field("**Email:**")
    linkedin = get_field("**LinkedIn:**")
    website = get_field("**Website:**")
    phone = get_field("**Phone:**")

    header_city_email = " | ".join([p for p in [city, email] if p])
    header_linkedin = linkedin
    header_website_phone = " | ".join([p for p in [website, phone] if p])

    sections: dict[str, list[str]] = {}
    current = None
    for ln in lines:
        if ln.strip() == "---":
            continue
        if ln.startswith("## "):
            current = ln[3:].strip().lower()
            sections[current] = []
            continue
        if current:
            sections[current].append(ln)

    # Summary paragraphs: split by blank lines
    summary_lines = [ln for ln in sections.get("summary", [])]
    summary = []
    buf: list[str] = []
    for ln in summary_lines:
        if not ln.strip():
            if buf:
                summary.append(" ".join(s.strip() for s in buf).strip())
                buf = []
            continue
        buf.append(ln)
    if buf:
        summary.append(" ".join(s.strip() for s in buf).strip())

    # Experience
    exp_lines = sections.get("experience", [])
    experience: list[ExperienceItem] = []
    i = 0
    while i < len(exp_lines):
        ln = exp_lines[i].strip()
        if ln.startswith("### "):
            title = ln[4:].strip()
            meta = ""
            bullets: list[str] = []
            skills = ""
            # next line expected: **Location | Dates**
            j = i + 1
            while j < len(exp_lines) and not exp_lines[j].strip():
                j += 1
            if j < len(exp_lines):
                meta = exp_lines[j].strip().strip("*").strip()
                i = j
            i += 1
            while i < len(exp_lines):
                cur = exp_lines[i].strip()
                if cur.strip() == "---":
                    i += 1
                    break
                if cur.startswith("### "):
                    break
                if cur.startswith("- "):
                    bullets.append(cur[2:].strip())
                elif cur.lower().startswith("*skills:"):
                    skills = cur.strip().strip("*").strip()
                    skills = re.sub(r"^skills:\s*", "", skills, flags=re.I).strip()
                i += 1
            experience.append(ExperienceItem(title=title, meta=meta, bullets=bullets, skills=skills))
            continue
        i += 1

    # Education (pairs)
    edu_lines = [ln.strip() for ln in sections.get("education", []) if ln.strip()]
    education: list[tuple[str, str]] = []
    i = 0
    while i < len(edu_lines):
        deg = edu_lines[i].strip("*").strip()
        nxt = edu_lines[i + 1] if i + 1 < len(edu_lines) else ""
        if nxt and not nxt.startswith("**"):
            education.append((deg, nxt))
            i += 2
        else:
            education.append((deg, ""))
            i += 1

    # Certifications
    certs = []
    for ln in sections.get("certifications", []):
        ln = ln.strip()
        if ln.startswith("- "):
            certs.append(ln[2:].strip())

    # Skills
    skills_pairs: list[tuple[str, str]] = []
    for ln in sections.get("skills", []):
        ln = ln.strip()
        if not ln:
            continue
        m = re.match(r"^\*{0,2}([^:]+?)\*{0,2}:\s*(.+)$", ln.strip("*").strip())
        if m:
            skills_pairs.append((m.group(1).strip(), m.group(2).strip()))

    # Languages
    languages: list[tuple[str, str]] = []
    for ln in sections.get("languages", []):
        ln = ln.strip()
        if ln.startswith("- "):
            item = ln[2:].strip()
            if "—" in item:
                a, b = [p.strip() for p in item.split("—", 1)]
                languages.append((a, b))
            elif "-" in item:
                a, b = [p.strip() for p in item.split("-", 1)]
                languages.append((a, b))
            else:
                languages.append((item, ""))

    return CVData(
        name=name,
        header_city_email=header_city_email,
        header_linkedin=header_linkedin,
        header_website_phone=header_website_phone,
        summary=summary,
        experience=experience,
        education=education,
        certifications=certs,
        skills=skills_pairs,
        languages=languages,
    )


# ── Rendering ───────────────────────────────────────────────────────────────────

def render_cv_pdf(md: str, out_path: Path) -> None:
    styles = build_styles()
    data = parse_cv_markdown(md)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=MARGIN_LR,
        rightMargin=MARGIN_LR,
        topMargin=MARGIN_TB,
        bottomMargin=MARGIN_TB,
        title=data.name or "CV",
        author=data.name or "",
    )

    story = []

    # Header (centered)
    story.append(Paragraph(escape(data.name), styles["header_name"]))
    if data.header_city_email:
        story.append(Paragraph(escape(data.header_city_email), styles["header_line"]))
    if data.header_linkedin:
        story.append(Paragraph(escape(data.header_linkedin), styles["header_line"]))
    if data.header_website_phone:
        story.append(Paragraph(escape(data.header_website_phone), styles["header_line"]))
    story.append(Spacer(1, 6))

    # Sections (in order)
    # Summary
    story.append(make_section_header("Summary", styles))
    story.append(Spacer(1, 4))
    for p in data.summary:
        story.append(Paragraph(escape(p), styles["body"]))
        story.append(Spacer(1, 3))
    story.append(hr())

    # Experience
    story.append(make_section_header("Experience", styles))
    story.append(Spacer(1, 4))
    for job in data.experience:
        story.append(Paragraph(escape(job.title), styles["job_title"]))
        if job.meta:
            story.append(Paragraph(escape(job.meta), styles["job_meta"]))
        for b in job.bullets:
            story.append(Paragraph(escape(b), styles["bullet"], bulletText="•"))
        if job.skills:
            story.append(Paragraph(escape(job.skills), styles["skill_tags"]))
        story.append(Spacer(1, 4))
    story.append(hr())

    # Education
    story.append(make_section_header("Education", styles))
    story.append(Spacer(1, 4))
    for degree, meta in data.education:
        # Degree bold dark navy (matches “Job title” style)
        story.append(Paragraph(escape(degree), styles["job_title"]))
        if meta:
            story.append(Paragraph(escape(meta), styles["job_meta"]))
        story.append(Spacer(1, 2))
    story.append(hr())

    # Certifications
    story.append(make_section_header("Certifications", styles))
    story.append(Spacer(1, 4))
    for c in data.certifications:
        story.append(Paragraph(escape(c), styles["bullet"], bulletText="•"))
    story.append(hr())

    # Skills (2-column table: label col 32mm wide)
    story.append(make_section_header("Skills", styles))
    story.append(Spacer(1, 4))

    skill_rows = []
    for label, value in data.skills:
        skill_rows.append([
            Paragraph(escape(label), styles["skills_label"]),
            Paragraph(escape(value), styles["skills_value"]),
        ])
    if skill_rows:
        t = Table(skill_rows, colWidths=[32 * mm, None])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(t)
    story.append(hr())

    # Languages (inline, separated by ·)
    story.append(make_section_header("Languages", styles))
    story.append(Spacer(1, 4))
    parts = []
    for name, level in data.languages:
        if level:
            parts.append(f"<b>{escape(name)}</b> — {escape(level)}")
        else:
            parts.append(f"<b>{escape(name)}</b>")
    story.append(Paragraph(" · ".join(parts), styles["lang_inline"]))

    doc.build(story)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="cv.md", help="Path to cv.md")
    ap.add_argument("--output", default="output/CV_Enrique_Wood_Rivero.pdf", help="Output PDF path")
    args = ap.parse_args()

    md = Path(args.input).read_text(encoding="utf-8")
    render_cv_pdf(md, Path(args.output))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

