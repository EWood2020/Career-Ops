#!/usr/bin/env python3
"""
Career-Ops: ATS-Optimized Application Generator
Generates tailored CV and cover letter for a specific LinkedIn job posting.

Usage:
    python3 apply.py https://www.linkedin.com/jobs/view/XXXXX/

Workflow:
1. Extract job ID, fetch JD via Playwright + li_at
2. Call Claude to score fit (1–5) and extract 15–20 ATS keywords
3. Generate tailored CV by injecting keywords into master cv.md
4. Generate personalized cover letter using profile.yml
5. Save to applications/{job-id}/ with analysis.json and README

Output:
    applications/{job-id}/
    ├── cv.md                    # Tailored CV in markdown
    ├── CV_Enrique_{Title}_{Company}.pdf  # Professionally formatted tailored CV
    ├── cover-letter.md          # Personalized cover letter
    ├── analysis.json            # Fit score, keywords, rationale
    └── README.md                # Job details + submission checklist
"""

import os
import re
import sys
import json
import logging
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import yaml
from playwright.sync_api import sync_playwright
import anthropic
from bs4 import BeautifulSoup
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Frame, PageTemplate, KeepInFrame, HRFlowable
from reportlab.lib.enums import TA_LEFT

from cover_letter_pdf import build_cover_letter
from build_cv import build_cv_pdf


# ─── LOGGING ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ─── PATHS & CONFIG ────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
PROFILE_PATH = SCRIPT_DIR / "profile.yml"
CV_PATH = SCRIPT_DIR / "cv.md"
APPLICATIONS_DIR = SCRIPT_DIR / "applications"
APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LINKEDIN_LI_AT = os.getenv("LINKEDIN_LI_AT", "")

CLAUDE_MODEL = "claude-haiku-4-5-20251001"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ─── LOAD CONFIG ────────────────────────────────────────────────────────────────

def load_profile() -> dict:
    """Load profile.yml positioning and metadata."""
    if not PROFILE_PATH.exists():
        log.error(f"Missing {PROFILE_PATH}")
        sys.exit(1)
    with open(PROFILE_PATH) as f:
        return yaml.safe_load(f) or {}


def load_cv() -> str:
    """Load master cv.md as source of truth."""
    if not CV_PATH.exists():
        log.error(f"Missing {CV_PATH}")
        sys.exit(1)
    with open(CV_PATH) as f:
        return f.read()


# ─── LINKEDIN JOB FETCHING ──────────────────────────────────────────────────────

def extract_job_id(url: str) -> str | None:
    """Extract LinkedIn job ID from URL."""
    match = re.search(r"/jobs/view/(\d+)", url)
    return match.group(1) if match else None


def fetch_linkedin_job(job_id: str) -> dict:
    """
    Fetch LinkedIn job posting via Playwright + li_at cookie.
    Extract: title, company, location, full job description.
    """
    if not LINKEDIN_LI_AT:
        log.error("LINKEDIN_LI_AT environment variable not set")
        sys.exit(1)

    url = f"https://www.linkedin.com/jobs/view/{job_id}/"
    log.info(f"Fetching LinkedIn job: {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=REQUEST_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            # Inject li_at cookie for authentication
            ctx.add_cookies([{
                "name": "li_at",
                "value": LINKEDIN_LI_AT,
                "domain": "www.linkedin.com",
                "path": "/",
            }])

            page = ctx.new_page()
            page.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2000)

            # Extract job title
            try:
                title_el = page.query_selector("h1, .top-card-layout__title, [data-test-id='job-title']")
                title = title_el.inner_text().strip() if title_el else "Unknown"
            except:
                title = "Unknown"

            # Extract company name
            try:
                company_el = page.query_selector("[data-test-id='job-card-subtitle-primary-desc'], .top-card-layout__company-name, a[href*='/company/']")
                company = company_el.inner_text().strip() if company_el else "Unknown"
            except:
                company = "Unknown"

            # Extract location (job subtitle details)
            location = ""
            try:
                # LinkedIn displays location in several places; try multiple selectors
                location_el = page.query_selector(
                    ".top-card-layout__metadata-item, "
                    "[data-test-id='job-details-location'], "
                    ".show-more-less-html__markup"
                )
                if location_el:
                    location_text = location_el.inner_text().strip()
                    # Location often appears as "City, Country" in the subtitle
                    if location_text and "," in location_text:
                        location = location_text
                    elif location_text:
                        # Fallback: extract first part if no comma
                        location = location_text.split("\n")[0]
            except:
                pass

            # If location not found by selector, try to extract from page text
            if not location:
                try:
                    page_text = page.text_content()
                    # Look for common location patterns
                    lines = page_text.split("\n")
                    for i, line in enumerate(lines):
                        line_clean = line.strip()
                        # Location often appears near company name or in metadata
                        if any(c.isupper() for c in line_clean) and len(line_clean) < 50:
                            if any(country in line_clean for country in ["Prague", "Amsterdam", "Barcelona", "Remote", "Europe", "CZ", "NL", "ES"]):
                                location = line_clean
                                break
                except:
                    pass

            # LinkedIn sometimes surfaces "Promoted" in the location slot
            if location and "promoted" in location.lower():
                location = ""

            # Extract full job description (all visible text)
            html_content = page.content()
            soup = BeautifulSoup(html_content, "html.parser")

            # Remove script, style, nav, header, footer
            for tag in soup(["script", "style", "nav", "header", "footer", "aside", "meta"]):
                tag.decompose()

            description = soup.get_text(separator=" ", strip=True)[:12000]

            browser.close()

            return {
                "job_id": job_id,
                "url": url,
                "title": title,
                "company": company,
                "location": location,
                "description": description,
            }

    except Exception as exc:
        log.error(f"Failed to fetch LinkedIn job {job_id}: {exc}")
        sys.exit(1)


# ─── CLAUDE SCORING & KEYWORD EXTRACTION ────────────────────────────────────────

def score_and_extract_keywords(
    job: dict,
    profile: dict,
    cv_text: str,
    client: anthropic.Anthropic,
) -> dict:
    """
    Call Claude to:
    1. Score fit (1.0–5.0) based on profile positioning
    2. Extract 15–20 ATS keywords from job description
    3. Rationale for fit decision

    Returns:
    {
        "fit_score": float,
        "fit_rationale": str,
        "keywords": [list of 15-20 keywords],
    }
    """
    profile_str = json.dumps(profile, indent=2)[:1000]
    cv_excerpt = cv_text[:1500]

    # Build JSON template as regular string (not f-string to avoid curly brace conflicts)
    json_template = """
{
  "fit_score": <float 1.0-5.0>,
  "fit_rationale": "<2 sentence reason for score>",
  "keywords": "<comma-separated list of 15-20 keywords>"
}
"""

    # Build prompt with f-string variables, then concatenate JSON template
    prompt = f"""
YOU ARE: ATS optimization expert + recruiter matching candidates to roles.

CANDIDATE PROFILE:
{profile_str}

CANDIDATE CV (excerpt):
{cv_excerpt}

JOB POSTING:
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Description:
{job.get('description', '')[:3000]}

TASK 1 — FIT SCORING (1.0–5.0):
Evaluate how well this job matches the candidate's profile.
- 5.0: Perfect match (exact target role, right seniority, aligned keywords)
- 4.0: Strong fit, minor gap (location or one missing skill)
- 3.0: Moderate fit, addressable gap
- 2.0: Partial fit, significant gap
- 1.0: Poor fit, unlikely to succeed

TASK 2 — ATS KEYWORDS:
Extract 15–20 keywords that:
- Appear in the job description
- Matter for ATS screening
- Are relevant to the candidate's background
- Include: roles, technologies, methodologies, industry terms, soft skills

Format keywords as comma-separated list (no quotes).

RESPONSE (ONLY JSON, no prose):
""" + json_template

    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()

        # Strip markdown code fences if present
        if "```" in text:
            parts = text.split("```")
            text = parts[1].strip()
            if text.startswith("json"):
                text = text[4:].strip()

        result = json.loads(text)
        # Parse keywords from comma-separated string to list
        if isinstance(result.get("keywords"), str):
            result["keywords"] = [k.strip() for k in result["keywords"].split(",")]
        return result

    except json.JSONDecodeError:
        log.error(f"Bad JSON from Claude: {text[:200]}")
        sys.exit(1)
    except Exception as exc:
        log.error(f"Claude API error: {exc}")
        sys.exit(1)


# ─── CV TAILORING ───────────────────────────────────────────────────────────────

def __make_keyword_sentence(keywords: list[str]) -> str:
    if not keywords:
        return ""
    if len(keywords) == 1:
        phrase = keywords[0]
    elif len(keywords) == 2:
        phrase = f"{keywords[0]} and {keywords[1]}"
    else:
        phrase = ", ".join(keywords[:-1]) + f", and {keywords[-1]}"
    return f"My approach combines {phrase} to deliver measurable results."


def _is_separator_paragraph(paragraph: str) -> bool:
    cleaned = paragraph.strip()
    return bool(cleaned) and re.fullmatch(r"[-\s]+", cleaned) is not None


def inject_keywords_naturally(text: str, keywords: list[str]) -> str:
    if not text.strip():
        return text
    keywords_to_add = [kw for kw in keywords if kw.lower() not in text.lower()][:3]
    if not keywords_to_add:
        return text

    paragraphs = re.split(r"\n\s*\n", text)
    trailing = []
    while paragraphs and (not paragraphs[-1].strip() or _is_separator_paragraph(paragraphs[-1])):
        trailing.insert(0, paragraphs.pop())

    if not paragraphs:
        return text

    last_idx = len(paragraphs) - 1
    for idx in range(len(paragraphs) - 1, -1, -1):
        if paragraphs[idx].strip() and not _is_separator_paragraph(paragraphs[idx]):
            last_idx = idx
            break

    last = paragraphs[last_idx].rstrip()
    addition = __make_keyword_sentence(keywords_to_add)
    if last.endswith((".", "!", "?")):
        paragraphs[last_idx] = f"{last} {addition}"
    else:
        paragraphs[last_idx] = f"{last}. {addition}"

    return "\n\n".join(paragraphs + trailing)


def generate_tailored_cv(cv_master: str, keywords: list, job_title: str, company: str, client: anthropic.Anthropic) -> str:
    """
    Rewrite CV summary and reorder experience bullets per job using Claude API.
    
    Claude will:
    1. Rewrite summary (2-3 paragraphs) targeting this specific role at company
    2. Inject keywords naturally (no keyword-stuffing, authentic prose)
    3. Reorder experience bullets to front-load relevance to this job
    
    Returns complete CV in markdown with all sections preserved.
    """
    keywords_str = ", ".join(keywords[:15])
    
    prompt = f"""You are an expert CV strategist. Your job is to rewrite a CV specifically for a job application.

TARGET ROLE:
- Position: {job_title}
- Company: {company}

INSTRUCTIONS:

1. SUMMARY REWRITE (2-3 paragraphs max):
   Rewrite the summary to directly address THIS specific role at {company}.
   - Keep all facts TRUE (no invented experience or skills)
   - Inject these keywords NATURALLY into the narrative (don't list them): {keywords_str}
   - Make it authentic—sound like the candidate, not a template
   - Highlight alignment with this specific role's requirements

2. EXPERIENCE REORDERING:
   For each role/position in the EXPERIENCE section, reorder the bullet points.
   - Move the most relevant accomplishments to the TOP of each role
   - Front-load results that match this job's keywords and requirements
   - Keep all original bullet points—just reorder them

3. PRESERVE EVERYTHING ELSE:
   - Keep all sections (Contact, Summary, Experience, Skills, Education, etc.)
   - Do not add fictional experience
   - Do not remove any existing content
   - Maintain markdown formatting

ORIGINAL CV:
{cv_master}

OUTPUT: Return ONLY the complete rewritten CV in markdown format. No explanations, no markdown code fences."""
    
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=3000,  # Increased from 2000 to handle longer CVs
            messages=[{"role": "user", "content": prompt}],
        )
        tailored = resp.content[0].text.strip()
        # If Claude wrapped it in markdown fences, unwrap
        if tailored.startswith("```markdown"):
            tailored = tailored[11:]
        if tailored.startswith("```"):
            tailored = tailored[3:]
        if tailored.endswith("```"):
            tailored = tailored[:-3]
        tailored = tailored.strip()
        log.info(f"✓ CV tailoring succeeded for {job_title} at {company}")
        return tailored
    except Exception as exc:
        log.error(f"✗ CV tailoring failed for {job_title} at {company}: {exc}")
        log.warning("Falling back to master CV - tailoring unsuccessful")
        # Fallback: return original CV
        return cv_master


# ─── COVER LETTER GENERATION ────────────────────────────────────────────────────

def generate_cover_letter(
    job: dict,
    profile: dict,
    keywords: list,
    cv_text: str,
    client: anthropic.Anthropic,
) -> str:
    """
    Generate personalized cover letter using Claude.
    Uses job details + profile positioning + CV proof points.
    """
    cv_excerpt = cv_text[:2000]
    keywords_str = ", ".join(keywords[:10])
    positioning = profile.get("positioning", {})
    one_liner = positioning.get("one_liner", "")

    prompt = f"""
YOU ARE: Expert cover letter writer for career-competitive tech roles.

CANDIDATE ONE-LINER:
{one_liner}

CV EXCERPT:
{cv_excerpt}

JOB POSTING:
Title: {job.get('title', '')}
Company: {job.get('company', '')}

KEY KEYWORDS FOR THIS ROLE:
{keywords_str}

TASK:
Write a personalized, authentic cover letter (3–4 paragraphs, ~250 words) that:
1. Opens with the role + company + why applying (specific to job description)
2. Highlights 2–3 proof points from CV that match job keywords
3. Closes with enthusiasm for the role and alignment with company challenge

Tone: Professional, specific to this job (NOT templated), authentic.
Keep it short; ATS prefers conciseness.

RESPONSE FORMAT (markdown):

# Cover Letter — {job['title']} at {job['company']}

Dear Hiring Team,

[Opening paragraph specific to this role]

[Proof point 1 with CV reference + keyword]

[Proof point 2 with CV reference + keyword]

[Closing: Why now, enthusiasm, call to action]

Best regards,
[Candidate name]
"""

    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as exc:
        log.error(f"Cover letter generation failed: {exc}")
        return ""


# ─── PDF GENERATION ─────────────────────────────────────────────────────────────

def build_cv_pdf_styles() -> dict:
    """Build reportlab styles for professional CV PDF generation."""
    NAVY = colors.HexColor("#1a1a2e")
    ACCENT = colors.HexColor("#2d6a4f")
    GREY = colors.HexColor("#666666")
    LIGHT_GREY = colors.HexColor("#f4f4f4")
    
    base = getSampleStyleSheet()
    
    return {
        # Header styles
        "name": ParagraphStyle(
            "Name", parent=base["Title"], fontSize=22,
            textColor=NAVY, fontName="Helvetica-Bold", spaceAfter=6,
            alignment=1,  # Center alignment
        ),
        "contact_bar": ParagraphStyle(
            "ContactBar", parent=base["Normal"], fontSize=9,
            textColor=NAVY, fontName="Helvetica", spaceAfter=12,
            backColor=LIGHT_GREY, borderColor=LIGHT_GREY, borderWidth=1,
            borderPadding=(6, 6, 6, 6), alignment=1,
        ),
        
        # Section headers with left border accent
        "section_header": ParagraphStyle(
            "SectionHeader", parent=base["Heading1"], fontSize=11,
            textColor=NAVY, fontName="Helvetica-Bold", spaceAfter=8,
            borderColor=ACCENT, borderWidth=0, borderPadding=(0, 0, 0, 4),
            leftIndent=0,
        ),
        
        # Body text
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontSize=9, leading=12,
            fontName="Helvetica", spaceAfter=4,
        ),
        "body_grey": ParagraphStyle(
            "BodyGrey", parent=base["Normal"], fontSize=9, leading=12,
            fontName="Helvetica", textColor=GREY, spaceAfter=2,
        ),
        "degree": ParagraphStyle(
            "Degree", parent=base["Normal"], fontSize=10, leading=12,
            fontName="Helvetica-Bold", textColor=NAVY, spaceAfter=1,
        ),
        
        # Experience styles
        "company": ParagraphStyle(
            "Company", parent=base["Normal"], fontSize=10,
            textColor=NAVY, fontName="Helvetica-Bold", spaceAfter=2,
        ),
        "role": ParagraphStyle(
            "Role", parent=base["Normal"], fontSize=10,
            textColor=ACCENT, fontName="Helvetica-Bold", spaceAfter=2,
        ),
        "dates": ParagraphStyle(
            "Dates", parent=base["Normal"], fontSize=9,
            textColor=GREY, fontName="Helvetica", alignment=2,  # Right align
        ),
        "bullet": ParagraphStyle(
            "Bullet", parent=base["Normal"], fontSize=9, leading=12,
            fontName="Helvetica", leftIndent=14, bulletIndent=6, spaceAfter=2,
        ),
        "skills_line": ParagraphStyle(
            "SkillsLine", parent=base["Normal"], fontSize=8,
            textColor=GREY, fontName="Helvetica-Oblique", spaceAfter=6,
        ),
        "experience_skills": ParagraphStyle(
            "ExperienceSkills", parent=base["Normal"], fontSize=9,
            textColor=GREY, fontName="Helvetica-Oblique", leftIndent=14,
            spaceAfter=6, leading=12,
        ),
        
        # Skills bullet style for categorized skills section
        "skill_bullet": ParagraphStyle(
            "SkillBullet", parent=base["Normal"], fontSize=9, leading=12,
            textColor=NAVY, fontName="Helvetica", leftIndent=14,
            bulletIndent=6, spaceAfter=2,
        ),
        "skills_line": ParagraphStyle(
            "SkillsLineInline", parent=base["Normal"], fontSize=9, leading=12,
            textColor=NAVY, fontName="Helvetica", spaceAfter=0,
        ),
        
        # Two-column layout styles
        "two_column": ParagraphStyle(
            "TwoColumn", parent=base["Normal"], fontSize=9, leading=11,
            fontName="Helvetica", spaceAfter=3,
        ),
    }


def escape_text(text: str) -> str:
    """Escape special characters for reportlab."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


def parse_cv_markdown(markdown: str) -> dict:
    """Parse CV markdown into structured data for PDF generation."""
    lines = markdown.splitlines()
    sections = {}
    current_section = None
    current_job = None
    
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        
        # Skip markdown horizontal rules
        if line.strip() == "---":
            i += 1
            continue

        # Header (name)
        if line.startswith("# "):
            sections["name"] = line[2:].strip()
            i += 1
            continue
            
        # Contact info (until ---)
        if "name" in sections and "contact" not in sections:
            contact_lines = []
            while i < len(lines) and not lines[i].strip().startswith("---"):
                if lines[i].strip() and not lines[i].strip().startswith("#"):
                    contact_lines.append(lines[i].strip())
                i += 1
            sections["contact"] = contact_lines
            i += 1  # Skip the ---
            continue
            
        # Section headers
        if line.startswith("## "):
            current_section = line[3:].strip().lower().replace(" ", "_")
            sections[current_section] = []
            i += 1
            continue
            
        # Experience job entries
        if current_section == "experience" and line.startswith("### "):
            job_title = line[4:].strip()
            # Look for company and dates in next line
            i += 1
            if i < len(lines):
                location_dates = lines[i].strip()
                # Parse: "Company | Location | Dates" or "Company | Dates"
                parts = [p.strip() for p in location_dates.split("|")]
                company = parts[0] if parts else ""
                location = ""
                dates = ""
                
                # Try to identify dates (contains year numbers)
                for part in parts[1:]:
                    if any(c.isdigit() for c in part):
                        dates = part
                    else:
                        location = part
                        
                current_job = {
                    "title": job_title,
                    "company": company,
                    "location": location,
                    "dates": dates,
                    "bullets": [],
                    "skills": ""
                }
                sections[current_section].append(current_job)
            continue
            
        # Experience bullets
        if current_section == "experience" and current_job and line.startswith("- "):
            current_job["bullets"].append(line[2:].strip())
            i += 1
            continue
            
        # Experience skills line
        if current_section == "experience" and current_job and line.lstrip().startswith("*Skills:"):
            skills_text = line.strip().strip("*").strip()
            if skills_text.lower().startswith("skills:"):
                skills_text = skills_text[len("skills:"):].strip()
            current_job["skills"] = skills_text
            i += 1
            continue
            
        # Other sections content (summary, education, certifications, skills, languages)
        if current_section and line.strip() and not line.startswith("- ") and not (line.startswith("*") and not line.startswith("**")) and not line.startswith("###"):
            if current_section not in ["experience"]:
                sections[current_section].append(line.strip())
            i += 1
            continue
            
        i += 1
    
    return sections


def generate_cv_pdf(markdown: str, output_path: Path):
    """Generate professionally formatted CV PDF with advanced layout."""
    styles = build_cv_pdf_styles()
    cv_data = parse_cv_markdown(markdown)
    elements = []
    
    # Page setup with 1.5cm margins
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )
    
    # Header section
    if "name" in cv_data:
        elements.append(Paragraph(escape_text(cv_data["name"]), styles["name"]))
    
    if "contact" in cv_data:
        contact_text = " | ".join(cv_data["contact"])
        elements.append(Paragraph(escape_text(contact_text), styles["contact_bar"]))
    
    # Add 0.4cm gap between header block and first section
    elements.append(Spacer(1, 0.4 * cm))
    
    # Process sections
    section_order = ["summary", "experience", "education", "certifications", "skills", "languages"]
    two_column_done = False
    
    for section_name in section_order:
        if section_name not in cv_data:
            continue
            
        # Skip certifications if we already did two-column with education
        if section_name == "certifications" and two_column_done:
            continue
            
        # Section header with left border accent
        section_title = section_name.replace("_", " ").title()
        elements.append(create_section_header(section_title, styles))
        elements.append(Spacer(1, 6))
        
        # Section content
        if section_name == "summary":
            content = cv_data[section_name]
            if isinstance(content, list):
                for paragraph in content:
                    elements.append(Paragraph(escape_text(paragraph), styles["body"]))
                    elements.append(Spacer(1, 4))
                    
        elif section_name == "experience":
            for job in cv_data[section_name]:
                # Company name (bold)
                elements.append(Paragraph(escape_text(job["company"]), styles["company"]))
                
                # Role title (colored) and dates (right-aligned)
                role_dates_table = create_role_dates_table(job["title"], job["dates"], styles)
                elements.append(role_dates_table)
                elements.append(Spacer(1, 4))
                
                # Bullets
                for bullet in job["bullets"]:
                    elements.append(Paragraph(escape_text(bullet), styles["bullet"], bulletText="•"))
                
                # Skills line
                if job["skills"]:
                    elements.append(Spacer(1, 2))
                    elements.append(Paragraph(escape_text(job["skills"]), styles["experience_skills"]))
                
                elements.append(Spacer(1, 8))
                
        elif section_name == "education":
            elements.extend(create_education_section(cv_data[section_name], styles))
            
        elif section_name == "certifications" and not two_column_done:
            # Only certifications, display normally
            for cert in cv_data[section_name]:
                elements.append(Paragraph(escape_text(cert), styles["body"]))
                
        elif section_name == "skills":
            skill_elements = create_skills_section(cv_data[section_name], styles)
            elements.extend(skill_elements)
            
        elif section_name == "languages":
            for lang in cv_data[section_name]:
                elements.append(Paragraph(escape_text(lang), styles["body"]))
        
        # Horizontal divider between sections
        elements.append(Spacer(1, 6))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
        elements.append(Spacer(1, 12))
    
    doc.build(elements)
    log.info(f"✓ Professional CV PDF saved: {output_path}")


def create_section_header(title: str, styles: dict):
    """Create section header with left border accent."""
    # Create a table with left border accent
    title_para = Paragraph(title.upper(), styles["section_header"])
    
    # Create table with colored left border
    table = Table(
        [[title_para]],
        colWidths=[None]
    )
    table.setStyle(TableStyle([
        ('LINEBEFORE', (0, 0), (0, 0), 4, colors.HexColor("#2d6a4f")),  # Left border
        ('LEFTPADDING', (0, 0), (0, 0), 8),
        ('TOPPADDING', (0, 0), (0, 0), 2),
        ('BOTTOMPADDING', (0, 0), (0, 0), 2),
    ]))
    return table


def create_role_dates_table(role: str, dates: str, styles: dict):
    """Create table with role title and right-aligned dates."""
    role_para = Paragraph(escape_text(role), styles["role"])
    dates_para = Paragraph(escape_text(dates), styles["dates"])
    
    table = Table(
        [[role_para, dates_para]],
        colWidths=[None, 4*cm]
    )
    table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (1, 0), 'TOP'),
    ]))
    return table


def format_education_item(item: str, styles: dict):
    """Format an education or certification line into a two-column row with dates aligned right."""
    if "|" in item:
        left_text, right_text = [part.strip() for part in item.split("|", 1)]
    else:
        left_text, right_text = item.strip(), ""

    left_para = Paragraph(escape_text(left_text), styles["two_column"])
    right_para = Paragraph(escape_text(right_text), styles["dates"]) if right_text else Paragraph("", styles["two_column"])

    row = Table(
        [[left_para, right_para]],
        colWidths=[10 * cm, 3 * cm]
    )
    row.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
    ]))
    return row


def create_two_column_section(left_data: list, right_data: list, styles: dict):
    """Create two-column layout for Education and Certifications."""
    left_flowables = []
    right_flowables = []

    for item in left_data:
        left_flowables.append(format_education_item(item, styles))
        left_flowables.append(Spacer(1, 6))

    for item in right_data:
        right_flowables.append(format_education_item(item, styles))
        right_flowables.append(Spacer(1, 6))

    left_column = KeepInFrame(8 * cm, 1000, left_flowables, mergeSpace=True)
    right_column = KeepInFrame(8 * cm, 1000, right_flowables, mergeSpace=True)

    table = Table(
        [[left_column, right_column]],
        colWidths=[8 * cm, 8 * cm]
    )
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    return [table, Spacer(1, 8)]

    return [table, Spacer(1, 8)]


def create_skills_section(skills_data: list, styles: dict):
    """Create Skills section from `**Category:** list` lines on a light grey background."""
    elements = []
    
    for skill_line in skills_data:
        cleaned_line = skill_line.strip()
        # Accept formats like:
        # **Strategic:** AI strategy, ...
        # Strategic: AI strategy, ...
        cleaned_line = cleaned_line.strip().strip("*").strip()
        match = re.match(r"^([^:]+?):\s*(.+)$", cleaned_line)
        if match:
            category = match.group(1).strip()
            skills = match.group(2).strip()
            line = Paragraph(
                f"<b>{escape_text(category)}:</b> {escape_text(skills)}",
                styles["skills_line"],
            )
            box = Table([[line]], colWidths=[None])
            box.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f4f4")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            elements.append(box)
            elements.append(Spacer(1, 6))

    return elements


def create_education_section(education_lines: list, styles: dict):
    """
    Render Education entries as:
    - degree bold
    - university normal weight
    - dates in grey on the same line (right-aligned)
    """
    elements = []
    i = 0
    while i < len(education_lines):
        line = (education_lines[i] or "").strip()
        if not line:
            i += 1
            continue

        degree = line.strip()
        # Markdown degree lines are typically `**...**`
        degree = degree.strip("*").strip()

        university = ""
        dates = ""

        if i + 1 < len(education_lines):
            nxt = (education_lines[i + 1] or "").strip()
            if nxt and not nxt.startswith("**"):
                # Expected: University | 2018–2019
                if "|" in nxt:
                    left_text, right_text = [p.strip() for p in nxt.split("|", 1)]
                    university = left_text
                    dates = right_text
                else:
                    university = nxt
                i += 1  # consume the university/dates line

        degree_para = Paragraph(escape_text(degree), styles["degree"])

        uni_para = Paragraph(escape_text(university), styles["body"]) if university else Paragraph("", styles["body"])
        dates_para = Paragraph(escape_text(dates), styles["dates"]) if dates else Paragraph("", styles["dates"])

        table = Table(
            [
                [degree_para, ""],
                [uni_para, dates_para],
            ],
            colWidths=[None, 4 * cm],
        )
        table.setStyle(TableStyle([
            ("SPAN", (0, 0), (1, 0)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 1), (1, 1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 6))

        i += 1

    return elements


# ─── FILE SAVING ────────────────────────────────────────────────────────────────

def save_application(
    folder_name: str,
    job: dict,
    analysis: dict,
    tailored_cv: str,
    cover_letter: str,
):
    """Save all artifacts to applications/{folder_name}/ directory."""
    app_dir = APPLICATIONS_DIR / folder_name
    app_dir.mkdir(parents=True, exist_ok=True)

    # Save analysis.json
    analysis_file = app_dir / "analysis.json"
    with open(analysis_file, "w") as f:
        json.dump(analysis, f, indent=2)
    log.info(f"✓ Saved {analysis_file.relative_to(SCRIPT_DIR)}")

    # Save tailored CV
    tailored_cv = (
        tailored_cv
        .replace("Czech Rectangle", "Czech Republic")
        .replace("Czech rect", "Czech Republic")
    )
    cv_file = app_dir / "cv.md"
    with open(cv_file, "w") as f:
        f.write(tailored_cv)
    log.info(f"✓ Saved {cv_file.relative_to(SCRIPT_DIR)}")

    # Save cover letter
    cl_file = app_dir / "cover-letter.md"
    with open(cl_file, "w") as f:
        f.write(cover_letter)
    log.info(f"✓ Saved {cl_file.relative_to(SCRIPT_DIR)}")

    # Generate tailored CV PDF with descriptive filename
    def sanitize_for_filename(text: str, max_len: int = 30) -> str:
        safe = re.sub(r"[^A-Za-z0-9 _-]", "", text or "")
        safe = re.sub(r"[\s]+", "_", safe).strip("_")
        return safe[:max_len] or "CV"
    
    job_title_clean = sanitize_for_filename(job.get("title", "job"))
    company_clean = sanitize_for_filename(job.get("company", "company"))
    pdf_filename = f"CV_Enrique_{job_title_clean}_{company_clean}.pdf"
    cv_pdf_file = app_dir / pdf_filename
    # Use the CV PDF template (ReportLab A4) for consistent styling
    try:
        build_cv_pdf(tailored_cv, cv_pdf_file)
        log.info(f"✓ CV PDF saved: {cv_pdf_file.name}")
    except Exception as exc:
        log.error(f"✗ CV PDF failed: {exc}")

    # Generate cover letter PDF (template-matched)
    cl_pdf_file = app_dir / f"CoverLetter_Enrique_{job_title_clean}_{company_clean}.pdf"
    try:
        if cl_file.exists():
            with open(cl_file, "r") as f:
                cl_md = f.read()

            paras: list[str] = []
            for line in cl_md.splitlines():
                s = line.strip()
                if not s:
                    continue
                if s.startswith("#"):
                    continue
                if s.startswith("Dear "):
                    continue
                if s.startswith("Best regards"):
                    continue
                if "Enrique Wood" in s:
                    continue
                if "+34" in s or "enriquewood.tech" in s:
                    continue
                paras.append(s)

            role_title = (job.get("title") or "").strip()
            if not role_title or role_title.lower() == "unknown":
                # Derive from folder_name (e.g. YYYY-MM-DD_Title_With_Underscores)
                derived = folder_name
                for prefix in ("FAILED_", "NON_LINKEDIN_"):
                    if derived.startswith(prefix):
                        derived = derived[len(prefix):]
                derived = derived.strip()
                if re.match(r"^\\d{4}-\\d{2}-\\d{2}_", derived):
                    derived = derived.split("_", 1)[1]
                role_title = derived.replace("_", " ").strip() or "Cover Letter"

            build_cover_letter(str(cl_pdf_file), role_title, paras)
            log.info(f"✓ Cover letter PDF: {cl_pdf_file.relative_to(SCRIPT_DIR)}")
    except Exception as exc:
        log.warning(f"Cover letter PDF generation failed: {exc}")

    # Save README with submission checklist
    readme_file = app_dir / "README.md"
    readme = f"""# Application: {job.get('title', '')} at {job.get('company', '')}

- **LinkedIn URL:** {job.get('url', '')}
- **Fit Score:** {analysis.get('fit_score', '')}
- **Rationale:** {analysis.get('fit_rationale', '')}
- **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Keywords Matched (ATS Optimization)
{', '.join(analysis.get('keywords', []))}

## Submission Checklist

- [ ] Review cv.md and cover-letter.md
- [ ] Verify keywords don't distort your narrative
- [ ] Check application portal rules (format, length)
- [ ] Submit via LinkedIn or company ATS
- [ ] Log submission to Google Sheets "tracked" tab
- [ ] Follow up in 1 week if no response

## Notes
Add any custom context for this application here.
"""
    with open(readme_file, "w") as f:
        f.write(readme)
    log.info(f"✓ Saved {readme_file.relative_to(SCRIPT_DIR)}")

    return app_dir


# ─── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 apply.py https://www.linkedin.com/jobs/view/XXXXX/")
        sys.exit(1)

    url = sys.argv[1]
    job_id = extract_job_id(url)

    if not job_id:
        log.error(f"Invalid LinkedIn job URL: {url}")
        sys.exit(1)

    log.info(f"=== Career-Ops ATS Application Generator ===")
    log.info(f"Job ID: {job_id}")
    
    # Fetch job details for folder naming
    job = fetch_linkedin_job(job_id)
    if not job:
        log.error("Failed to fetch job details")
        sys.exit(1)
    
    # Create readable folder name: YYYY-MM-DD_Job_Title
    today = datetime.now().strftime("%Y-%m-%d")
    def sanitize_for_folder(text: str, max_len: int = 30) -> str:
        safe = re.sub(r"[^A-Za-z0-9 _-]", "", text or "")
        safe = re.sub(r"[\s]+", "_", safe).strip("_")
        safe = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", safe)
        tokens = [token for token in safe.split("_") if token]
        collapsed = []
        for token in tokens:
            if not collapsed or token.lower() != collapsed[-1].lower():
                collapsed.append(token)
        safe = "_".join(collapsed)
        return safe[:max_len] or "Unknown"
    
    job_title_clean = sanitize_for_folder(job.get("title", "Job"))
    folder_name = f"{today}_{job_title_clean}"

    # Load candidate profile and CV
    log.info("Loading profile and master CV...")
    profile = load_profile()
    cv_master = load_cv()

    # Fetch LinkedIn job
    log.info("Fetching LinkedIn job posting...")
    job = fetch_linkedin_job(job_id)
    log.info(f"Title: {job['title']}")
    log.info(f"Company: {job['company']}")

    # Score fit and extract keywords
    log.info("Scoring fit and extracting ATS keywords...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    analysis = score_and_extract_keywords(job, profile, cv_master, client)
    log.info(f"Fit Score: {analysis['fit_score']}/5.0")
    log.info(f"Keywords: {', '.join(analysis['keywords'][:5])}...")

    # Check fit threshold
    if analysis["fit_score"] < 3.5:
        log.warning(f"Fit score {analysis['fit_score']} below 3.5 threshold—not worth tailoring")
        sys.exit(0)

    # Generate tailored CV
    log.info("Generating tailored CV with keyword injection...")
    tailored_cv = generate_tailored_cv(cv_master, analysis["keywords"], job["title"], job["company"], client)

    # Generate cover letter
    log.info("Generating personalized cover letter...")
    cover_letter = generate_cover_letter(job, profile, analysis["keywords"], cv_master, client)

    # Save all artifacts
    log.info("Saving application artifacts...")
    app_dir = save_application(folder_name, job, analysis, tailored_cv, cover_letter)

    log.info(f"✓ Application ready at: {app_dir.relative_to(SCRIPT_DIR)}/")
    log.info(f"Next: Review the files and submit via LinkedIn/ATS")


if __name__ == "__main__":
    main()
