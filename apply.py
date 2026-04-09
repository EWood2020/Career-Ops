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
    ├── cv.md                    # Tailored CV with keyword injection
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
    Extract: title, company, full job description.
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


def generate_tailored_cv(cv_master: str, keywords: list, job_title: str) -> str:
    """
    Generate tailored CV by:
    1. Injecting keywords naturally into summary + experience
    2. Prioritizing bullets that match keywords
    3. Keeping master structure intact

    Returns tailored CV markdown.
    """
    lines = cv_master.split("\n")
    output = []
    in_summary = False
    in_experience = False
    summary_buffer = []

    def flush_summary_buffer():
        if not summary_buffer:
            return []
        summary_text = "\n".join(summary_buffer).strip()
        keywords_to_inject = [kw for kw in keywords if kw.lower() not in summary_text.lower()][:3]
        if keywords_to_inject:
            summary_text = inject_keywords_naturally(summary_text, keywords_to_inject)
        # Preserve blank line paragraphs
        paragraphs = re.split(r"\n\s*\n", summary_text)
        flushed = []
        for idx, paragraph in enumerate(paragraphs):
            flushed.extend(paragraph.split("\n"))
            if idx < len(paragraphs) - 1:
                flushed.append("")
        return flushed

    for line in lines:
        if line.lower().startswith("## summary"):
            in_summary = True
            in_experience = False
            output.append(line)
            continue

        if line.lower().startswith("## experience"):
            output.extend(flush_summary_buffer())
            summary_buffer = []
            in_summary = False
            in_experience = True
            output.append(line)
            continue

        if in_summary:
            summary_buffer.append(line)
            continue

        output.append(line)

    if summary_buffer:
        output.extend(flush_summary_buffer())

    return "\n".join(output)


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


# ─── FILE SAVING ────────────────────────────────────────────────────────────────

def save_application(
    job_id: str,
    job: dict,
    analysis: dict,
    tailored_cv: str,
    cover_letter: str,
):
    """Save all artifacts to applications/{job-id}/ directory."""
    app_dir = APPLICATIONS_DIR / job_id
    app_dir.mkdir(parents=True, exist_ok=True)

    # Save analysis.json
    analysis_file = app_dir / "analysis.json"
    with open(analysis_file, "w") as f:
        json.dump(analysis, f, indent=2)
    log.info(f"✓ Saved {analysis_file.relative_to(SCRIPT_DIR)}")

    # Save tailored CV
    cv_file = app_dir / "cv.md"
    with open(cv_file, "w") as f:
        f.write(tailored_cv)
    log.info(f"✓ Saved {cv_file.relative_to(SCRIPT_DIR)}")

    # Save cover letter
    cl_file = app_dir / "cover-letter.md"
    with open(cl_file, "w") as f:
        f.write(cover_letter)
    log.info(f"✓ Saved {cl_file.relative_to(SCRIPT_DIR)}")

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
    tailored_cv = generate_tailored_cv(cv_master, analysis["keywords"], job["title"])

    # Generate cover letter
    log.info("Generating personalized cover letter...")
    cover_letter = generate_cover_letter(job, profile, analysis["keywords"], cv_master, client)

    # Save all artifacts
    log.info("Saving application artifacts...")
    app_dir = save_application(job_id, job, analysis, tailored_cv, cover_letter)

    log.info(f"✓ Application ready at: {app_dir.relative_to(SCRIPT_DIR)}/")
    log.info(f"Next: Review the files and submit via LinkedIn/ATS")


if __name__ == "__main__":
    main()
