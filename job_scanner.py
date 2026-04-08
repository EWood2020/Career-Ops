#!/usr/bin/env python3
"""
Daily Job Scanner — Career-Ops for Enrique Wood Rivero
Scans job boards via RSS and scraping, scores each role against
profile.yml using Claude API, logs to Google Sheets, and generates
a daily briefing PDF.

Setup:
    pip install -r requirements.txt

Environment variables required:
    ANTHROPIC_API_KEY            — Anthropic/Claude API key
    GOOGLE_SHEET_ID              — Google Spreadsheet ID (from sheet URL)
    GOOGLE_SERVICE_ACCOUNT_JSON  — Path to service account credentials JSON
    JOB_SCANNER_OUTPUT_DIR       — Output dir for PDFs/logs (default: ./output)

Google Sheets expected structure:
    "tracked"  tab → date | title | url          (deduplication gate)
    "pipeline" tab → date | job_title | company | url | score | fit_pct | salary_ask | verdict | why
    "skipped"  tab → date | job_title | company | url | score | verdict | why
"""

import os
import sys
import json
import time
import logging
import datetime
from pathlib import Path
from urllib.parse import urlencode, urljoin

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import yaml
import feedparser
import requests
from bs4 import BeautifulSoup
import anthropic
import gspread
from google.oauth2.service_account import Credentials
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT


# ─── PATHS & ENVIRONMENT ────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
PROFILE_PATH = SCRIPT_DIR / "profile.yml"
PORTALS_PATH = SCRIPT_DIR / "portals.yml"
OUTPUT_DIR = Path(os.getenv("JOB_SCANNER_OUTPUT_DIR", SCRIPT_DIR / "output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_SA_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

CLAUDE_MODEL = "claude-sonnet-4-6"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 15


# ─── LOGGING ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(OUTPUT_DIR / "scanner.log"),
    ],
)
log = logging.getLogger(__name__)


# ─── RSS FEED DEFINITIONS ───────────────────────────────────────────────────────
# Boards with known working public RSS. LinkedIn RSS works sporadically —
# included with graceful fallback.

RSS_FEEDS = [
    {
        "name": "We Work Remotely — Management",
        "url": "https://weworkremotely.com/categories/remote-management-finance-jobs.rss",
    },
    {
        "name": "Remotive — Business & Management",
        "url": "https://remotive.io/remote-jobs/feed/?category=business-%26-management",
    },
    {
        "name": "Working Nomads",
        "url": "https://www.workingnomads.com/feed?pub=1",
    },
    {
        "name": "LinkedIn — AI transformation consultant Europe",
        "url": "https://www.linkedin.com/jobs/search/rss?"
               + urlencode({"keywords": "AI transformation consultant", "location": "Europe", "f_WT": "2"}),
    },
    {
        "name": "LinkedIn — digital transformation consultant Europe",
        "url": "https://www.linkedin.com/jobs/search/rss?"
               + urlencode({"keywords": "digital transformation consultant", "location": "Europe", "f_WT": "2"}),
    },
    {
        "name": "LinkedIn — AI strategy consultant Europe",
        "url": "https://www.linkedin.com/jobs/search/rss?"
               + urlencode({"keywords": "AI strategy consultant", "location": "Europe", "f_WT": "2"}),
    },
    {
        "name": "LinkedIn — AI enablement lead Europe",
        "url": "https://www.linkedin.com/jobs/search/rss?"
               + urlencode({"keywords": "AI enablement lead", "location": "Europe"}),
    },
    {
        "name": "LinkedIn — head of AI transformation",
        "url": "https://www.linkedin.com/jobs/search/rss?"
               + urlencode({"keywords": "head of AI transformation", "location": "Europe"}),
    },
    {
        "name": "LinkedIn — digital transformation Prague",
        "url": "https://www.linkedin.com/jobs/search/rss?"
               + urlencode({"keywords": "digital transformation consultant", "location": "Prague"}),
    },
    {
        "name": "LinkedIn — technology strategy consultant Lisbon",
        "url": "https://www.linkedin.com/jobs/search/rss?"
               + urlencode({"keywords": "technology strategy consultant", "location": "Lisbon"}),
    },
]


# ─── TITLE FILTERS ──────────────────────────────────────────────────────────────
# Auto-skip before calling Claude API to save tokens (per agent-job-scanner.md).

ENGINEERING_KEYWORDS = [
    "ml engineer", "machine learning engineer", "data scientist",
    "python developer", "python dev", "backend engineer", "backend developer",
    "software engineer", "software developer", "rag engineer", "llm engineer",
    "prompt engineer", "data engineer", "analytics engineer",
    "devops engineer", "frontend engineer", "full stack engineer",
    "junior", "graduate", "intern", "apprentice",
]


def is_engineering_role(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in ENGINEERING_KEYWORDS)


def mentions_lisbon(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in ["lisbon", "lisboa", "portugal", "porto"])


# ─── GOOGLE SHEETS ──────────────────────────────────────────────────────────────

def get_sheet() -> gspread.Spreadsheet:
    creds = Credentials.from_service_account_file(GOOGLE_SA_JSON, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(GOOGLE_SHEET_ID)


def get_existing_urls(sheet: gspread.Spreadsheet) -> set:
    try:
        ws = sheet.worksheet("tracked")
        col = ws.col_values(3)      # URL is column C
        return {v.strip() for v in col[1:] if v.strip()}   # skip header row
    except gspread.WorksheetNotFound:
        log.info("Creating 'tracked' worksheet")
        ws = sheet.add_worksheet("tracked", rows=5000, cols=3)
        ws.append_row(["date", "title", "url"])
        return set()


def mark_tracked(sheet: gspread.Spreadsheet, job: dict, today: str):
    try:
        ws = sheet.worksheet("tracked")
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet("tracked", rows=5000, cols=3)
        ws.append_row(["date", "title", "url"])
    ws.append_row([today, job.get("job_title", "")[:200], job.get("url", "")])


def ensure_ws(sheet: gspread.Spreadsheet, name: str, headers: list) -> gspread.Worksheet:
    try:
        return sheet.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(name, rows=5000, cols=len(headers))
        ws.append_row(headers)
        return ws


PIPELINE_HEADERS = [
    "date", "job_title", "company", "url",
    "score", "fit_pct", "salary_ask", "verdict", "why",
]
SKIPPED_HEADERS = ["date", "job_title", "company", "url", "score", "verdict", "why"]


def append_pipeline(sheet: gspread.Spreadsheet, job: dict, result: dict, today: str):
    ws = ensure_ws(sheet, "pipeline", PIPELINE_HEADERS)
    ws.append_row([
        today,
        job.get("job_title", ""),
        job.get("company", ""),
        job.get("url", ""),
        result.get("score", ""),
        result.get("fit_pct", ""),
        str(result.get("salary_ask") or ""),
        result.get("verdict", ""),
        result.get("why", ""),
    ])


def append_skipped(sheet: gspread.Spreadsheet, job: dict, result: dict, today: str):
    ws = ensure_ws(sheet, "skipped", SKIPPED_HEADERS)
    ws.append_row([
        today,
        job.get("job_title", ""),
        job.get("company", ""),
        job.get("url", ""),
        result.get("score", ""),
        result.get("verdict", ""),
        result.get("why", ""),
    ])


# ─── FETCHING ───────────────────────────────────────────────────────────────────

def fetch_rss(feed: dict) -> list:
    name, url = feed["name"], feed["url"]
    log.info(f"RSS ← {name}")
    try:
        parsed = feedparser.parse(url)
        jobs = []
        for entry in parsed.entries:
            title = entry.get("title", "").strip()
            link  = entry.get("link", "").strip()
            if not title or not link:
                continue
            company = (
                entry.get("author", "")
                or (entry.get("source") or {}).get("title", "")
            )
            jobs.append({
                "job_title":   title,
                "url":         link,
                "company":     company,
                "description": entry.get("summary", ""),
                "date_posted": entry.get("published", ""),
                "source":      name,
            })
        log.info(f"   {len(jobs)} entries")
        return jobs
    except Exception as exc:
        log.warning(f"RSS failed ({name}): {exc}")
        return []


def fetch_page_text(url: str, cap: int = 8000) -> str:
    """Download a job posting page and return clean text (capped)."""
    try:
        r = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code in (401, 403, 429):
            log.warning(f"Blocked {r.status_code}: {url}")
            return ""
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "meta"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)[:cap]
    except Exception as exc:
        log.warning(f"Page fetch failed ({url}): {exc}")
        return ""


def scrape_company_page(company: dict) -> list:
    """Extract job-link candidates from a company careers page."""
    name, url = company["name"], company["url"]
    log.info(f"Scraping: {name}")
    try:
        r = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code in (401, 403, 429):
            log.warning(f"Blocked {r.status_code}: {name}")
            return []
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        jobs = []
        seen_urls: set = set()
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = a["href"]
            if not text or not (8 <= len(text) <= 200):
                continue
            if href.startswith("/"):
                href = urljoin(url, href)
            elif not href.startswith("http"):
                continue
            if href in seen_urls:
                continue
            # Heuristic: URL or link text looks like a job posting
            href_l = href.lower()
            text_l = text.lower()
            is_job = (
                any(kw in href_l for kw in [
                    "job", "career", "position", "role", "opening",
                    "vacancy", "apply", "requisition", "hiring",
                ]) or
                any(kw in text_l for kw in [
                    "consultant", "manager", "lead", "head of", "director",
                    "strategist", "advisor", "analyst", "officer", "specialist",
                    "transformation", "strategy", "ai ", "digital",
                ])
            )
            if is_job:
                seen_urls.add(href)
                jobs.append({
                    "job_title":   text,
                    "url":         href,
                    "company":     name,
                    "description": "",
                    "date_posted": "",
                    "source":      f"Company: {name}",
                })
        log.info(f"   {min(len(jobs), 25)} links from {name}")
        return jobs[:25]
    except Exception as exc:
        log.warning(f"Scrape failed ({name}): {exc}")
        return []


# ─── CLAUDE SCORING ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a job fit evaluator for a specific candidate profile.

Candidate: Enrique Wood Rivero
Primary positioning: AI Transformation Lead / Digital Strategy — business side
Key proof points:
- Production AI agent systems (competitor intel, content automation, market research) — deployed in code, 24/7
- Global adoption roadmap at MSD (multinational pharma)
- Obeya facilitation between engineering teams — accelerated cross-functional decisions
- 25 transformation projects pilot→steady state at Quint Group (regulated energy sector)
- AI Foundation Sprint methodology: process mapping, SSOT, data governance before AI

Fit signals (positive): business-side AI, org change, LEAN/ITIL/governance, consulting/advisory,
cross-functional stakeholder management, regulated industry (pharma, energy, finance),
Prague or Lisbon or remote Europe

Fit signals (negative): deep ML/Python engineering, no stakeholder interaction, pure data science,
STEM hard filter required

Target compensation: 65K–85K EUR gross/year
Location: Prague (current) | Lisbon (preferred relocation) | Remote Europe

Evaluate the job posting. Return ONLY valid JSON, no prose:
{
  "score": <float 1.0-5.0>,
  "fit_pct": <integer 0-100>,
  "salary_ask": "<string or null>",
  "verdict": "<apply|hold|skip>",
  "why": "<2 sentence max rationale>"
}

Scoring guide:
5.0 = perfect title + org change + regulated + right location
4.0-4.9 = strong fit, minor gap (location or one missing signal)
3.0-3.9 = partial fit, worth logging for review
< 3.0 = skip"""


def score_job(client: anthropic.Anthropic, job: dict) -> dict | None:
    user_msg = (
        f"Job Title: {job.get('job_title', 'Unknown')}\n"
        f"Company: {job.get('company', 'Unknown')}\n"
        f"URL: {job.get('url', '')}\n"
        f"Posted: {job.get('date_posted', 'Unknown')}\n\n"
        f"Job Description:\n"
        f"{job.get('full_description') or job.get('description') or '(No description available)'}"
    )
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip()
        # Strip markdown code fences if present
        if "```" in text:
            parts = text.split("```")
            text = parts[1].strip()
            if text.startswith("json"):
                text = text[4:].strip()
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning(f"Bad JSON from Claude for '{job.get('job_title')}': {text[:200]}")
        return None
    except Exception as exc:
        log.warning(f"Claude error for '{job.get('job_title')}': {exc}")
        return None


# ─── PDF GENERATION ─────────────────────────────────────────────────────────────

NAVY   = colors.HexColor("#1a1a2e")
GREEN  = colors.HexColor("#2d6a4f")
AMBER  = colors.HexColor("#e07c24")
SILVER = colors.HexColor("#f4f4f4")
LIGHT  = colors.HexColor("#f8f9fa")


def build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title", parent=base["Title"], fontSize=20, spaceAfter=4,
            textColor=NAVY, fontName="Helvetica-Bold",
        ),
        "subtitle": ParagraphStyle(
            "Sub", parent=base["Normal"], fontSize=9,
            textColor=colors.grey, spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontSize=13,
            spaceBefore=14, spaceAfter=5, textColor=NAVY,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["Normal"], fontSize=9, leading=13,
        ),
        "small": ParagraphStyle(
            "Small", parent=base["Normal"], fontSize=8,
            textColor=colors.grey, leading=11,
        ),
        "job_title": ParagraphStyle(
            "JobTitle", parent=base["Normal"], fontSize=11,
            fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=3,
        ),
        "italic": ParagraphStyle(
            "Italic", parent=base["Normal"], fontSize=9,
            leading=13, fontName="Helvetica-Oblique",
        ),
    }


def cell(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(str(text), style)


def generate_pdf(
    pipeline: list,
    partial_fits: list,
    output_path: Path,
    today: str,
    stats: dict,
):
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    S = build_styles()
    story = []

    # ── Header ──
    story.append(Paragraph(f"Daily Job Briefing — {today}", S["title"]))
    story.append(Paragraph("Career-Ops · Enrique Wood Rivero", S["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY))
    story.append(Spacer(1, 0.4 * cm))

    # ── Stats summary ──
    stats_data = [
        ["Sources", "Fetched", "New", "Scored", "Pipeline ≥4.0", "Skipped <4.0"],
        [
            str(stats.get("sources_scanned", 0)),
            str(stats.get("total_fetched", 0)),
            str(stats.get("new_jobs", 0)),
            str(stats.get("scored", 0)),
            str(len(pipeline)),
            str(stats.get("skipped_score", 0)),
        ],
    ]
    st = Table(stats_data, colWidths=[2.8 * cm] * 6)
    st.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("FONTNAME",      (0, 1), (-1, 1), "Helvetica-Bold"),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [LIGHT]),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(st)
    story.append(Spacer(1, 0.5 * cm))

    # ── Pipeline section ──
    story.append(Paragraph(
        f"Pipeline — Apply Now  ({len(pipeline)} role{'s' if len(pipeline) != 1 else ''})",
        S["h2"],
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=GREEN))
    story.append(Spacer(1, 0.2 * cm))

    if pipeline:
        for idx, item in enumerate(pipeline, 1):
            job    = item["job"]
            result = item["result"]
            score  = result.get("score", "?")
            fit    = result.get("fit_pct", "?")
            salary = str(result.get("salary_ask") or "Not stated")
            why    = result.get("why", "")
            source = job.get("source", "")
            url    = job.get("url", "")

            story.append(Paragraph(
                f"{idx}. {job.get('job_title', 'Untitled')} — {job.get('company', '?')}",
                S["job_title"],
            ))
            detail = Table(
                [
                    ["Score", "Fit %", "Salary Ask", "Verdict", "Source"],
                    [str(score), f"{fit}%", salary, result.get("verdict","").upper(), source],
                ],
                colWidths=[2 * cm, 2 * cm, 4 * cm, 2 * cm, 6.5 * cm],
            )
            detail.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#e8f5e9")),
                ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",      (0, 0), (-1, -1), 8),
                ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("GRID",          (0, 0), (-1, -1), 0.3, colors.grey),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(detail)
            story.append(Spacer(1, 0.15 * cm))
            story.append(Paragraph(f"<i>{why}</i>", S["italic"]))
            story.append(Paragraph(
                f'<link href="{url}" color="blue">{url}</link>', S["small"]
            ))
            story.append(Spacer(1, 0.4 * cm))
    else:
        story.append(Paragraph("No roles scored ≥ 4.0 today.", S["body"]))
        story.append(Spacer(1, 0.3 * cm))

    # ── Partial fits section (3.0–3.9) ──
    if partial_fits:
        story.append(Paragraph(
            f"Partial Fits — Worth a Look  ({len(partial_fits)} roles, score 3.0–3.9)",
            S["h2"],
        ))
        story.append(HRFlowable(width="100%", thickness=1, color=AMBER))
        story.append(Spacer(1, 0.2 * cm))

        partial_data = [[
            cell("Score", S["body"]),
            cell("Title", S["body"]),
            cell("Company", S["body"]),
            cell("Why", S["body"]),
        ]]
        for item in partial_fits:
            job    = item["job"]
            result = item["result"]
            partial_data.append([
                cell(str(result.get("score", "?")), S["body"]),
                cell(job.get("job_title", "")[:60], S["small"]),
                cell(job.get("company", "")[:35], S["small"]),
                cell(result.get("why", "")[:120], S["small"]),
            ])

        pt = Table(partial_data, colWidths=[1.5 * cm, 5.5 * cm, 4 * cm, 5.5 * cm])
        pt.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#fff3e0")),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("ALIGN",         (0, 0), (0, -1), "CENTER"),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("GRID",          (0, 0), (-1, -1), 0.3, colors.grey),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, LIGHT]),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(pt)
        story.append(Spacer(1, 0.3 * cm))

    # ── Footer ──
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        f"Generated by Career-Ops Job Scanner · "
        f"{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC",
        S["small"],
    ))

    doc.build(story)
    log.info(f"PDF saved: {output_path}")


# ─── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    today = datetime.date.today().isoformat()
    log.info(f"=== Job Scanner starting — {today} ===")

    # Load portals config
    with open(PORTALS_PATH) as f:
        portals = yaml.safe_load(f)

    # Initialise clients
    claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    sheet  = get_sheet()

    # Deduplication gate: URLs already in "tracked" tab
    existing_urls = get_existing_urls(sheet)
    log.info(f"Tracked URLs already in sheet: {len(existing_urls)}")

    # ── Step 1: Collect job candidates ──────────────────────────────────────────
    all_jobs: list[dict] = []
    sources_scanned = 0

    # RSS feeds
    for feed in RSS_FEEDS:
        all_jobs.extend(fetch_rss(feed))
        sources_scanned += 1
        time.sleep(1)

    # Company career pages (very-high and high fit only)
    for company in portals.get("tracked_companies", []):
        if company.get("fit") in ("very-high", "high"):
            all_jobs.extend(scrape_company_page(company))
            sources_scanned += 1
            time.sleep(2)

    total_fetched = len(all_jobs)
    log.info(f"Total fetched: {total_fetched} from {sources_scanned} sources")

    # ── Step 2: Deduplicate ──────────────────────────────────────────────────────
    seen_urls: set = set(existing_urls)
    deduped: list[dict] = []
    for job in all_jobs:
        url = job.get("url", "").strip()
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped.append(job)
    log.info(f"New (after dedup): {len(deduped)}")

    # ── Step 3: Pre-filter engineering roles ────────────────────────────────────
    to_score: list[dict] = []
    auto_skipped = 0
    for job in deduped:
        if is_engineering_role(job.get("job_title", "")):
            log.info(f"Auto-skip (engineering): {job['job_title'][:60]}")
            mark_tracked(sheet, job, today)
            auto_skipped += 1
        else:
            to_score.append(job)
    log.info(f"To score: {len(to_score)} ({auto_skipped} engineering auto-skipped)")

    # ── Step 4: Score with Claude API ───────────────────────────────────────────
    pipeline_jobs:  list[dict] = []   # score >= 4.0 → "pipeline" tab
    partial_fits:   list[dict] = []   # score 3.0–3.9 → PDF partial section
    scored_count = 0
    skipped_score_count = 0

    for i, job in enumerate(to_score, 1):
        log.info(f"[{i}/{len(to_score)}] {job['job_title'][:65]}")

        # Fetch full page text when description is too short
        if len(job.get("description", "")) < 200:
            job["full_description"] = fetch_page_text(job["url"])
            time.sleep(1)
        else:
            job["full_description"] = job["description"]

        result = score_job(claude, job)
        if result is None:
            log.warning(f"Scoring failed — marking tracked and skipping")
            mark_tracked(sheet, job, today)
            continue

        scored_count += 1
        score = float(result.get("score", 0))

        # Apply +0.5 Lisbon/Portugal bonus (cap at 5.0)
        context_text = " ".join([
            job.get("job_title", ""),
            job.get("full_description", ""),
            job.get("url", ""),
        ])
        if mentions_lisbon(context_text):
            score = min(score + 0.5, 5.0)
            result["score"] = round(score, 1)
            result["why"] = (result.get("why", "") + " [+0.5 Lisbon/Portugal bonus]").strip()
            log.info(f"   Lisbon bonus → score now {score}")

        # Mark as tracked (dedup gate)
        mark_tracked(sheet, job, today)

        # Route by score
        if score >= 4.0:
            log.info(f"   PIPELINE ✓  score={score}  verdict={result.get('verdict')}")
            append_pipeline(sheet, job, result, today)
            pipeline_jobs.append({"job": job, "result": result})
        else:
            skipped_score_count += 1
            log.info(f"   skipped  score={score}")
            append_skipped(sheet, job, result, today)
            if score >= 3.0:
                partial_fits.append({"job": job, "result": result})

        time.sleep(0.5)   # light rate-limit between Claude calls

    # Sort pipeline by score descending for PDF
    pipeline_jobs.sort(key=lambda x: float(x["result"].get("score", 0)), reverse=True)

    # ── Step 5: Generate PDF briefing ───────────────────────────────────────────
    stats = {
        "sources_scanned": sources_scanned,
        "total_fetched":   total_fetched,
        "new_jobs":        len(deduped),
        "scored":          scored_count,
        "skipped_score":   skipped_score_count,
    }
    pdf_path = OUTPUT_DIR / f"job_briefing_{today}.pdf"
    generate_pdf(pipeline_jobs, partial_fits, pdf_path, today, stats)

    # ── Summary ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Job Scanner — {today}")
    print(f"{'='*60}")
    print(f"Sources scanned : {sources_scanned}")
    print(f"Jobs fetched    : {total_fetched}")
    print(f"New (deduped)   : {len(deduped)}")
    print(f"Scored by Claude: {scored_count}")
    print(f"Pipeline (≥4.0) : {len(pipeline_jobs)}")
    print(f"Partial (3-3.9) : {len(partial_fits)}")
    print(f"PDF briefing    : {pdf_path}")
    print(f"{'='*60}\n")

    log.info("=== Job Scanner complete ===")


if __name__ == "__main__":
    main()
