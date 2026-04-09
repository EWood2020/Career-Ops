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
    "pipeline" tab → date | job_title | company | location | url | score | fit_pct | salary_ask | verdict | why
    "skipped"  tab → date | job_title | company | url | score | verdict | why
"""

import os
import re
import sys
import json
import time
import logging
import datetime
import tempfile
from pathlib import Path
import random
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from urllib.parse import urlencode, urljoin, quote_plus

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import yaml
import feedparser
from playwright.sync_api import sync_playwright
import requests
from bs4 import BeautifulSoup
import anthropic
import apply
from cover_letter_pdf import build_cover_letter
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
_sa_content = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT", "")
if _sa_content:
    # Railway double-escapes backslashes — parse as JSON string directly
    try:
        _sa_dict = json.loads(_sa_content)
    except json.JSONDecodeError:
        # Fallback: manual fix for double-escaped newlines only
        _sa_content = _sa_content.replace("\\\\n", "\\n")
        _sa_dict = json.loads(_sa_content)
    _tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(_sa_dict, _tmp)
    _tmp.flush()
    GOOGLE_SA_JSON = _tmp.name
else:
    GOOGLE_SA_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
LINKEDIN_LI_AT = os.getenv("LINKEDIN_LI_AT", "")

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
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
        "name": "EuroJobSites — management/strategy",
        "url": "https://www.eurojobs.com/rss/management-consulting.xml",
    },
    {
        "name": "JobFluent — Europe (English)",
        "url": "https://www.jobfluent.com/rss/jobs.xml",
    },
    {
        "name": "Jobgether — remote Europe",
        "url": "https://jobgether.com/feed/remote-jobs.xml",
    },
    # Otta has no RSS feed; add to Playwright company scrapers separately.
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


# Fix 1 — job-title signal gate: anchor text must contain at least one of these
# to be considered a real job posting (blocks nav/CTA/region links).
ROLE_TEXT_SIGNALS = [
    "consultant", "manager", "lead", "director", "analyst",
    "strategist", "engineer", "specialist", "head of", "officer",
    "advisor", "associate",
]

SCORING_TITLE_KEYWORDS = [
    "transformation", "strategy", "ai", "digital", "consultant",
    "enablement", "governance", "advisory", "intelligence",
    "change management", "product owner", "innovation",
]


def has_scoring_keyword(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in SCORING_TITLE_KEYWORDS)


def has_role_signal(text: str) -> bool:
    t = text.lower()
    return any(re.search(r"\b" + re.escape(sig) + r"\b", t) for sig in ROLE_TEXT_SIGNALS)


def is_engineering_role(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in ENGINEERING_KEYWORDS)


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
        ws = sheet.worksheet(name)
        existing_headers = ws.row_values(1)
        if existing_headers != headers:
            # Keep worksheet schema aligned to headers (removes noisy extra columns)
            try:
                ws.resize(cols=len(headers))
            except Exception:
                # Resize may fail with some worksheet protections; header update still helps alignment.
                pass
            ws.update("A1", [headers])
        return ws
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(name, rows=5000, cols=len(headers))
        ws.append_row(headers)
        return ws


PIPELINE_HEADERS = [
    "date", "job_title", "company", "location", "url",
    "score", "fit_pct", "salary_ask", "verdict", "why",
]
SKIPPED_HEADERS = ["date", "job_title", "company", "location", "url", "score", "verdict", "why"]


def append_pipeline(sheet: gspread.Spreadsheet, job: dict, result: dict, today: str, folder_name: str = ""):
    ws = ensure_ws(sheet, "pipeline", PIPELINE_HEADERS)
    ws.append_row([
        today,
        job.get("job_title", ""),
        job.get("company", ""),
        job.get("location", "Not specified"),
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
        job.get("location", "Not specified"),
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


def normalize_text_fixes(text: str) -> str:
    """Small global text normalizations for consistent outputs."""
    if not text:
        return text
    return text.replace("Czech Rectangle", "Czech Republic")


def extract_cover_letter_body_paragraphs(md_text: str) -> list[str]:
    """
    Extract cover letter body paragraphs from markdown, excluding greeting/signature.
    Expects typical structure:
      # Cover Letter ...
      Dear Hiring Team,
      <paragraphs...>
      Best regards,
      <name>
      <contact>
    """
    if not md_text:
        return []

    # Drop markdown headings and keep meaningful lines.
    raw_lines = []
    for ln in md_text.splitlines():
        s = ln.strip()
        if not s:
            raw_lines.append("")  # preserve paragraph boundaries
            continue
        if s.startswith("#"):
            continue
        raw_lines.append(s)

    # Split into paragraphs on blank lines.
    paras: list[str] = []
    buf: list[str] = []
    for ln in raw_lines:
        if ln == "":
            if buf:
                paras.append(" ".join(buf).strip())
                buf = []
            continue
        buf.append(ln)
    if buf:
        paras.append(" ".join(buf).strip())

    cleaned: list[str] = []
    for p in paras:
        pl = p.lower().strip()
        if pl.startswith("dear "):
            continue
        if pl.startswith("best regards"):
            continue
        if "enrique wood rivero" in pl:
            continue
        if "+34" in p or "enriquewood.tech" in pl:
            continue
        cleaned.append(p)

    return cleaned


# Fix 2 — companies that render via JS and need Playwright
PLAYWRIGHT_COMPANIES = {"Sia Partners", "ServiceNow", "Roche", "Novartis"}

# Href patterns that indicate an actual job posting page
JOB_HREF_PATTERNS = ["/job/", "/jobs/", "/careers/", "/position/", "/vacancy/",
                     "/opening/", "/requisition/", "/apply/"]


def _is_job_href(href: str) -> bool:
    h = href.lower()
    return any(p in h for p in JOB_HREF_PATTERNS)


def scrape_company_page(company: dict) -> list:
    """Extract job-link candidates from a company careers page (static HTTP)."""
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
            # Fix 1: anchor text must contain a role signal keyword
            if not has_role_signal(text):
                continue
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


def scrape_company_page_playwright(company: dict) -> list:
    """
    Render a JS-heavy careers page with headless Chromium (same pattern as
    alza-local/local.js): stealth header patch, scroll 8×, extract links
    that match job-href patterns AND pass the role-signal text filter.
    """
    name, url = company["name"], company["url"]
    log.info(f"Playwright scrape: {name}")
    jobs = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            # Stealth: mask navigator.webdriver
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )
            page = ctx.new_page()
            page.set_extra_http_headers({
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2500)   # let SPA hydrate

            # Scroll 8× like alza-local/local.js
            for _ in range(8):
                page.mouse.wheel(0, 900)
                page.wait_for_timeout(400)

            # Extract all anchors
            raw_links = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => ({text: e.innerText.trim(), href: e.getAttribute('href')}))"
            )
            browser.close()

        seen_urls: set = set()
        for link in raw_links:
            text = (link.get("text") or "").strip()
            href = (link.get("href") or "").strip()
            if not text or not href or not (8 <= len(text) <= 200):
                continue
            if href.startswith("/"):
                href = urljoin(url, href)
            elif not href.startswith("http"):
                continue
            if href in seen_urls:
                continue
            # Fix 2: href must look like a job page AND text must pass role signal
            if not _is_job_href(href) or not has_role_signal(text):
                continue
            seen_urls.add(href)
            jobs.append({
                "job_title":   text,
                "url":         href,
                "company":     name,
                "description": "",
                "date_posted": "",
                "source":      f"Company/PW: {name}",
            })

        log.info(f"   {len(jobs)} job links from {name} (Playwright)")
        return jobs[:30]
    except Exception as exc:
        log.warning(f"Playwright scrape failed ({name}): {exc}")
        return []


# Fix 3 — LinkedIn Playwright scraper with li_at cookie injection
LINKEDIN_QUERIES = [
    ("AI transformation consultant", "Europe"),
    ("digital transformation consultant", "Europe"),
    ("AI strategy consultant", "Europe"),
    ("AI enablement lead", "Europe"),
    ("head of AI transformation", "Europe"),
    ("digital transformation consultant", "Prague"),
    ("senior product manager AI", "Europe"),
]

# Matches authenticated LinkedIn job-view URLs only
LINKEDIN_JOB_URL_RE = re.compile(r"linkedin\.com/jobs/view/\d+")


def scrape_linkedin_playwright() -> list:
    """
    Scrape LinkedIn job search results using li_at session cookie.
    - maxConcurrency: 1 (sequential queries, same as alza-local pattern)
    - Scroll 8× per page
    - 2–3 s jitter between queries
    - Extracts only /jobs/view/<id> URLs
    - Applies role-signal text filter on job card titles
    """
    if not LINKEDIN_LI_AT:
        log.info("LINKEDIN_LI_AT not set — skipping LinkedIn Playwright scraper")
        return []

    all_jobs: list[dict] = []
    log.info(f"LinkedIn Playwright: {len(LINKEDIN_QUERIES)} queries")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        # Stealth patch
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        # Inject li_at session cookie — authenticates the session
        ctx.add_cookies([{
            "name":   "li_at",
            "value":  LINKEDIN_LI_AT,
            "domain": "www.linkedin.com",
            "path":   "/",
            "secure": True,
            "httpOnly": True,
        }])

        page = ctx.new_page()
        page.set_extra_http_headers({
            "Accept-Language": "en-US,en;q=0.9",
        })

        # Warm up session: land on feed first so the li_at cookie is honoured
        # before navigating to search (avoids ERR_TOO_MANY_REDIRECTS)
        try:
            page.goto("https://linkedin.com/feed/", wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(2000)
        except Exception as exc:
            log.warning(f"LinkedIn feed warm-up failed: {exc}")

        for keywords, location in LINKEDIN_QUERIES:
            search_url = (
                "https://www.linkedin.com/jobs/search/?"
                + urlencode({"keywords": keywords, "location": location, "f_WT": "2"})
            )
            log.info(f"  LinkedIn ← {keywords} / {location}")
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(3000)   # SPA render buffer

                # Scroll 8× to load lazy job cards (mirrors alza-local scroll loop)
                for _ in range(8):
                    page.mouse.wheel(0, 900)
                    page.wait_for_timeout(500)

                page.wait_for_timeout(2000)
                current_url = page.url
                log.info(f"  Page URL after scroll: {current_url}")

                all_hrefs = page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => e.href).filter(h => h)"
                )
                jobs_view_count = sum(1 for h in all_hrefs if '/jobs/view/' in h)
                log.info(
                    f"  Total hrefs on page: {len(all_hrefs)}, containing /jobs/view/: {jobs_view_count}"
                )

                raw_links = page.eval_on_selector_all(
                    "a[href]",
                    """els => els.map(e => {
                        const href = e.href || '';
                        const text = (e.innerText || e.getAttribute('aria-label') || '').trim();
                        let location = '';
                        const jobCard = e.closest('li, .job-card-list__entity, .jobs-search-results__list-item, .result-card, .job-card-container');
                        if (jobCard) {
                            const locEl = jobCard.querySelector('.job-card-container__metadata-item, .job-card-list__location, .job-card__location, .job-card-layout__location, [data-test-job-location], .job-card-container__footer-item');
                            if (locEl) {
                                location = locEl.innerText.trim();
                            }
                        }
                        return { href, text, location };
                    })"""
                )
                jobs_view_count = sum(
                    1 for link in raw_links
                    if link.get("href") and "/jobs/view/" in link.get("href")
                )
                log.info(f"LinkedIn raw href links: {len(raw_links)}, jobs/view count: {jobs_view_count}")

                found = 0
                for link in raw_links:
                    href = (link.get("href") or "").strip()
                    text = (link.get("text") or "").strip()
                    location = (link.get("location") or "").strip()
                    if location and "promoted" in location.lower():
                        location = ""
                    if not href or not LINKEDIN_JOB_URL_RE.search(href):
                        continue
                    # Normalise to canonical job URL (strip tracking params)
                    match = LINKEDIN_JOB_URL_RE.search(href)
                    clean_url = "https://www." + match.group(0) + "/"
                    # Apply role-signal filter (Fix 1)
                    if text and not has_role_signal(text):
                        continue
                    all_jobs.append({
                        "job_title":   text or "LinkedIn job",
                        "url":         clean_url,
                        "company":     "",
                        "location":    location or "Not specified",
                        "description": "",
                        "date_posted": "",
                        "source":      f"LinkedIn/PW: {keywords}",
                    })
                    found += 1

                log.info(f"     {found} job cards extracted")

            except Exception as exc:
                log.warning(f"  LinkedIn query failed ({keywords}): {exc}")

            # 2–3 s jitter between queries (maxConcurrency: 1)
            time.sleep(random.uniform(2.0, 3.0))

        browser.close()

    log.info(f"LinkedIn Playwright total: {len(all_jobs)} job cards")
    return all_jobs


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
Prague or remote Europe

Fit signals (negative): deep ML/Python engineering, no stakeholder interaction, pure data science,
STEM hard filter required

Target compensation: 65K–85K EUR gross/year
Location: Prague (current) | Amsterdam | Barcelona | Basque Country | Remote Europe

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
        f"{normalize_text_fixes(job.get('full_description') or job.get('description') or '(No description available)')}"
    )
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
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
        result = json.loads(text)
        # Defensive: normalize common text glitches from model outputs
        if isinstance(result, dict) and isinstance(result.get("why"), str):
            result["why"] = normalize_text_fixes(result["why"])
        return result
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


def sanitize_filename(text: str, max_len: int = 40) -> str:
    safe = re.sub(r"[^A-Za-z0-9 _-]", "", text or "")
    safe = re.sub(r"[\s]+", "_", safe).strip("_")
    return safe[:max_len] or "file"


def build_cv_styles() -> dict:
    base = getSampleStyleSheet()
    styles = build_styles()
    styles.update({
        "cv_title": ParagraphStyle(
            "CVTitle", parent=base["Title"], fontSize=16,
            textColor=NAVY, fontName="Helvetica-Bold", spaceAfter=6,
        ),
        "cv_heading": ParagraphStyle(
            "CVHeading", parent=base["Heading2"], fontSize=12,
            textColor=NAVY, fontName="Helvetica-Bold", spaceAfter=4,
        ),
        "cv_subheading": ParagraphStyle(
            "CVSubheading", parent=base["Normal"], fontSize=10,
            textColor=NAVY, fontName="Helvetica-Bold", spaceAfter=3,
        ),
        "cv_body": ParagraphStyle(
            "CVBody", parent=base["Normal"], fontSize=9, leading=12,
        ),
        "cv_bullet": ParagraphStyle(
            "CVBullet", parent=base["Normal"], fontSize=9, leading=12,
            leftIndent=14, bulletIndent=6,
        ),
    })
    return styles


def escape_text(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


def generate_cv_pdf_from_markdown(markdown: str, output_path: Path):
    styles = build_cv_styles()
    elements = []
    for line in markdown.splitlines():
        stripped = line.rstrip()
        if not stripped:
            elements.append(Spacer(1, 4))
            continue
        if stripped.startswith("# "):
            elements.append(Paragraph(escape_text(stripped[2:]), styles["cv_title"]))
            continue
        if stripped.startswith("## "):
            elements.append(Paragraph(escape_text(stripped[3:]), styles["cv_heading"]))
            continue
        if stripped.startswith("### "):
            elements.append(Paragraph(escape_text(stripped[4:]), styles["cv_subheading"]))
            continue
        if stripped.startswith("- "):
            elements.append(Paragraph(escape_text(stripped[2:]), styles["cv_bullet"], bulletText="•"))
            continue
        elements.append(Paragraph(escape_text(stripped), styles["cv_body"]))

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    doc.build(elements)
    log.info(f"CV PDF saved: {output_path}")


def generate_cv_pdf_from_markdown_file(markdown_path: Path, output_path: Path):
    with open(markdown_path, "r") as f:
        markdown = f.read()
    generate_cv_pdf_from_markdown(markdown, output_path)


def cell(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(str(text), style)


def generate_profile_analysis(pipeline: list, partial_fits: list, client: anthropic.Anthropic) -> str:
    """
    Generate market positioning summary using Claude.
    Analyzes pipeline roles and returns insights on:
    - Market positioning summary
    - Top 3 role archetypes with count
    - Geography distribution
    - Avg score comparison
    - Recommended focus for today
    """
    if not pipeline:
        return "No pipeline roles today. Focus on: (1) Refreshing job feeds; (2) Expanding company career page tracking; (3) Building CV keyword optimization."
    
    # Extract insights from pipeline
    titles = [item["job"]["job_title"] for item in pipeline]
    companies = [item["job"]["company"] for item in pipeline]
    locations = [item["job"].get("location", "Unknown") for item in pipeline]
    scores_pipeline = [float(item["result"].get("score", 0)) for item in pipeline]
    scores_partial = [float(item["result"].get("score", 0)) for item in partial_fits] if partial_fits else []
    
    avg_pipeline = sum(scores_pipeline) / len(scores_pipeline) if scores_pipeline else 0
    avg_partial = sum(scores_partial) / len(scores_partial) if scores_partial else 0
    
    # Count role archetypes (simple heuristic: group by keywords in title)
    archetype_keywords = {
        "transformation": ["transformation", "transform", "digital"],
        "strategy": ["strategy", "strategic", "lead"],
        "implementation": ["implementation", "deliver", "execution"],
        "advisory": ["advisor", "consultant", "advisory"],
        "AI/ML": ["AI", "machine learning", "data science", "ML"],
    }
    
    archetype_counts = {}
    for title in titles:
        title_lower = title.lower()
        matched = False
        for archetype, keywords in archetype_keywords.items():
            if any(kw in title_lower for kw in keywords):
                archetype_counts[archetype] = archetype_counts.get(archetype, 0) + 1
                matched = True
                break
        if not matched:
            archetype_counts["other"] = archetype_counts.get("other", 0) + 1
    
    # Top 3 archetypes
    top_3 = sorted(archetype_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    archetype_str = "; ".join([f"{k}({v})" for k, v in top_3])
    
    # Geography distribution
    location_counts = {}
    for loc in locations:
        if loc and loc != "Unknown":
            # Extract country/city
            key = loc.split(",")[-1].strip() if "," in loc else loc[:20]
            location_counts[key] = location_counts.get(key, 0) + 1
    
    geo_str = ", ".join([f"{k}({v})" for k, v in sorted(location_counts.items(), key=lambda x: x[1], reverse=True)[:5]])
    
    # Build Claude prompt for insights
    prompt = f"""You are a career market analyst. Today's job search data:

PIPELINE DATA (≥3.5 score):
- {len(pipeline)} roles found
- Average fit score: {avg_pipeline:.2f}/5.0
- Top archetypes: {archetype_str}
- Geography: {geo_str}

CONTEXT:
- Comparing to {len(partial_fits)} partial-fit roles (3.0-3.9 score, avg {avg_partial:.2f}/5.0)
- Candidate positioning: AI Transformation Lead / Digital Strategy — business side
- Target: Prague or remote Europe

TASK:
Generate a 2-3 sentence market positioning summary for today that:
1. Describes the role archetypes found today
2. Compares pipeline quality vs partial fit quality  
3. Recommends which role type to prioritize applying to first (based on archetype, geography, fit score)

Format as a single paragraph (no bullet points). Be concise and actionable."""
    
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = resp.content[0].text.strip()
        return analysis
    except Exception as exc:
        log.error(f"Profile analysis generation failed: {exc}")
        # Fallback
        return f"Today's market: {len(pipeline)} pipeline roles (avg score {avg_pipeline:.2f}), {len(partial_fits)} partial fits (avg {avg_partial:.2f}). Top archetypes: {archetype_str}. Geography: {geo_str}. Recommendation: Apply to top scorer first, then work down by fit score."


def generate_pdf(
    pipeline: list,
    partial_fits: list,
    output_path: Path,
    today: str,
    stats: dict,
    client: anthropic.Anthropic | None = None,
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

    # ── Profile Analysis Section ──
    if client:
        analysis_text = generate_profile_analysis(pipeline, partial_fits, client)
        story.append(Paragraph("📊 Today's Market Positioning", S["h2"]))
        story.append(Paragraph(analysis_text, S["body"]))
        story.append(Spacer(1, 0.4 * cm))

    # ── Stats summary ──
    stats_data = [
        ["Sources", "Fetched", "New", "Scored", "Pipeline ≥3.5", "Skipped <3.5"],
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
            location = job.get("location", "Not specified")
            url    = job.get("url", "")

            # Make company name more prominent
            story.append(Paragraph(
                f"{idx}. <b>{job.get('job_title', 'Untitled')}</b>",
                S["job_title"],
            ))
            story.append(Paragraph(
                f"<b>{job.get('company', 'Unknown Company')}</b> — {location}",
                S["body"],
            ))
            detail = Table(
                [
                    ["Score", "Fit %", "Salary Ask", "Location", "Verdict", "Source"],
                    [str(score), f"{fit}%", salary, location, result.get("verdict", "").upper(), source],
                ],
                colWidths=[2 * cm, 2 * cm, 3.5 * cm, 3 * cm, 2 * cm, 4.5 * cm],
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
        story.append(Paragraph("No roles scored ≥ 3.5 today.", S["body"]))
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
            cell("Location", S["body"]),
            cell("URL", S["body"]),
            cell("Why", S["body"]),
        ]]
        for item in partial_fits:
            job    = item["job"]
            result = item["result"]
            url    = job.get("url", "")
            partial_data.append([
                cell(str(result.get("score", "?")), S["body"]),
                cell(job.get("job_title", "")[:50], S["small"]),
                cell(job.get("company", "")[:30], S["small"]),
                cell(job.get("location", "Not specified")[:30], S["small"]),
                cell(f'<link href="{url}" color="blue">{url[:40]}...</link>' if url else "", S["small"]),
                cell(result.get("why", "")[:100], S["small"]),
            ])

        pt = Table(partial_data, colWidths=[1.5 * cm, 4.5 * cm, 3 * cm, 2.8 * cm, 3.7 * cm, 3 * cm])
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
    story.append(Paragraph(
        '<link href="https://docs.google.com/spreadsheets/d/1u13Vf6W4gOZI50QvrzUk7N9mc5izc1vigLjQJxFdVFs" color="blue">View Full Results in Google Sheets</link>',
        S["small"],
    ))

    doc.build(story)
    log.info(f"PDF saved: {output_path}")


# ─── EMAIL NOTIFICATIONS ──────────────────────────────────────────────────────

def generate_html_email_body(pipeline_jobs: list, partial_fits: list, stats: dict, today: str, sheet_url: str = "") -> str:
    """Generate professional HTML email body with inline CSS (mobile-responsive)."""
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; color: #333; background-color: #f5f5f5; }}
        .container {{ max-width: 700px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: white; padding: 30px 20px; border-radius: 8px 8px 0 0; text-align: center; }}
        .header h1 {{ font-size: 24px; margin-bottom: 5px; }}
        .header p {{ font-size: 12px; opacity: 0.9; }}
        .stats-table {{ width: 100%; background: white; padding: 20px; border-collapse: collapse; }}
        .stats-table tr {{ border-bottom: 1px solid #eee; }}
        .stats-table td {{ padding: 10px; font-size: 13px; }}
        .stats-table .label {{ font-weight: 600; color: #1a1a2e; width: 40%; }}
        .stats-table .value {{ text-align: right; color: #2d6a4f; font-weight: bold; }}
        .section-title {{ background: #2d6a4f; color: white; padding: 12px 20px; font-weight: bold; font-size: 14px; margin-top: 0; }}
        .section-title.partial {{ background: #e07c24; }}
        .job-card {{ background: white; padding: 20px; margin-bottom: 15px; border-left: 4px solid #2d6a4f; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        .job-card.partial {{ border-left-color: #e07c24; }}
        .job-title {{ font-size: 16px; font-weight: 700; color: #1a1a2e; margin-bottom: 5px; }}
        .company-location {{ font-size: 13px; color: #666; margin-bottom: 10px; }}
        .details-row {{ display: flex; justify-content: space-between; font-size: 12px; margin: 8px 0; }}
        .detail-label {{ font-weight: 600; color: #555; }}
        .detail-value {{ color: #2d6a4f; font-weight: 500; }}
        .score-badge {{ display: inline-block; background: #2d6a4f; color: white; padding: 4px 10px; border-radius: 3px; font-size: 12px; font-weight: bold; margin-right: 8px; }}
        .rationale {{ font-size: 12px; color: #666; margin: 10px 0; font-style: italic; }}
        .url-link {{ display: inline-block; background: #f0f0f0; padding: 8px 12px; border-radius: 3px; text-decoration: none; color: #0066cc; font-size: 11px; word-break: break-word; }}
        .empty-message {{ text-align: center; padding: 20px; color: #999; font-size: 13px; }}
        .footer {{ background: #f9f9f9; padding: 20px; text-align: center; font-size: 12px; color: #666; border-top: 1px solid #eee; }}
        .footer a {{ color: #0066cc; text-decoration: none; }}
        @media (max-width: 600px) {{
            .container {{ padding: 10px; }}
            .details-row {{ flex-direction: column; }}
            .detail-value {{ margin-top: 3px; }}
            .job-card {{ padding: 15px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 Career-Ops Daily Briefing</h1>
            <p>{today}</p>
        </div>
        
        <table class="stats-table">
            <tr>
                <td class="label">Sources Scanned</td>
                <td class="value">{stats.get('sources_scanned', 0)}</td>
            </tr>
            <tr>
                <td class="label">Jobs Fetched</td>
                <td class="value">{stats.get('total_fetched', 0)}</td>
            </tr>
            <tr>
                <td class="label">New (Deduped)</td>
                <td class="value">{stats.get('new_jobs', 0)}</td>
            </tr>
            <tr>
                <td class="label">Scored by Claude</td>
                <td class="value">{stats.get('scored', 0)}</td>
            </tr>
            <tr style="background: #f0f7f0; font-weight: bold;">
                <td class="label">Pipeline (≥3.5)</td>
                <td class="value" style="color: #2d6a4f; font-size: 16px;">{len(pipeline_jobs)}</td>
            </tr>
        </table>
        
        <div class="section-title">✅ APPLY NOW — Pipeline Roles ({len(pipeline_jobs)})</div>
        <div style="background: white; padding: 20px;">
"""

    if pipeline_jobs:
        for idx, item in enumerate(pipeline_jobs, 1):
            job = item["job"]
            result = item["result"]
            location = job.get("location", "Location not specified")
            salary = str(result.get("salary_ask", "Not stated"))
            score = result.get("score", "?")
            fit_pct = result.get("fit_pct", "?")
            why = result.get("why", "")
            url = job.get("url", "")
            
            html += f"""
        <div class="job-card">
            <div class="job-title">{idx}. {job.get('job_title', 'Untitled')}</div>
            <div class="company-location"><strong>{job.get('company', 'Unknown Company')}</strong> • {location}</div>
            <div class="details-row">
                <span><span class="detail-label">Score:</span> <span class="score-badge">{score}/5.0</span></span>
                <span><span class="detail-label">Fit:</span> <span class="detail-value">{fit_pct}%</span></span>
                <span><span class="detail-label">Salary:</span> <span class="detail-value">{salary}</span></span>
            </div>
            <div class="rationale">{why}</div>
            <a href="{url}" class="url-link">View on LinkedIn →</a>
        </div>
"""
    else:
        html += '<div class="empty-message">No roles scored ≥ 3.5 today. Keep building momentum!</div>\n'
    
    html += """        </div>"""
    
    if partial_fits:
        html += f"""
        
        <div class="section-title partial">🟡 PARTIAL FITS — Worth Looking ({len(partial_fits)} roles, score 3.0–3.9)</div>
        <div style="background: white; padding: 20px;">
"""
        for item in partial_fits[:10]:  # Limit to 10 to avoid email bloat
            job = item["job"]
            result = item["result"]
            location = job.get("location", "—")
            score = result.get("score", "?")
            why = result.get("why", "")
            url = job.get("url", "")
            
            html += f"""
        <div class="job-card partial">
            <div class="job-title">{job.get('job_title', 'Untitled')[:60]}</div>
            <div class="company-location"><strong>{job.get('company', '?')[:40]}</strong> • {location[:30]}</div>
            <div class="details-row">
                <span><span class="detail-label">Score:</span> <span class="detail-value">{score}/5.0</span></span>
                <span><span class="detail-label">Why:</span> <span class="detail-value">{why[:50]}...</span></span>
            </div>
            <a href="{url}" class="url-link">View →</a>
        </div>
"""
        html += """        </div>"""
        
        if len(partial_fits) > 10:
            html += f"""<div style="text-align: center; padding: 15px; color: #999; font-size: 12px;">... +{len(partial_fits) - 10} more partial fits in PDF briefing</div>"""
    
    html += """
        
        <div class="footer">
            <p><strong>💡 Pro Tip:</strong> Check the attached PDF briefing for detailed stats and all partial-fit roles.</p>
"""
    
    if sheet_url:
        html += f"""<p><a href="{sheet_url}">📊 View full pipeline in Google Sheets →</a></p>
"""
    
    html += """
            <p style="margin-top: 15px; border-top: 1px solid #ddd; padding-top: 15px; color: #999;">
                Career-Ops Daily Briefing | Powered by Claude Haiku
            </p>
        </div>
    </div>
</body>
</html>
"""
    return html


def send_email_briefing(
    pipeline_jobs: list,
    partial_fits: list,
    stats: dict,
    today: str,
    pdf_path: Path,
    cv_paths: list[dict] | None = None,
):
    """Send Daily briefing via Gmail with PDF + CV attachments (HTML email)."""
    gmail_address = os.getenv("GMAIL_ADDRESS", "")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD", "")
    google_sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    
    if not gmail_address or not gmail_password:
        log.warning("GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set — skipping email notification")
        return
    
    try:
        sheet_url = f"https://docs.google.com/spreadsheets/d/{google_sheet_id}/edit" if google_sheet_id else ""
        html_body = generate_html_email_body(pipeline_jobs, partial_fits, stats, today, sheet_url)
        plain_body = f"Career-Ops Daily Briefing {today} — {len(pipeline_jobs)} pipeline roles\nSee HTML version for full details."
        
        subject = f"Career-Ops Daily Briefing {today} — {len(pipeline_jobs)} pipeline roles"
        message = MIMEMultipart("mixed")
        message["From"] = gmail_address
        message["To"] = gmail_address
        message["Subject"] = subject

        alternative = MIMEMultipart("alternative")
        alternative.attach(MIMEText(plain_body, "plain"))
        alternative.attach(MIMEText(html_body, "html"))
        message.attach(alternative)
        
        if pdf_path.exists():
            with open(pdf_path, "rb") as attachment:
                part = MIMEBase("application", "pdf")
                part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={pdf_path.name}")
            message.attach(part)

        if cv_paths:
            for cv_meta in cv_paths:
                if isinstance(cv_meta, dict):
                    cv_pdf_file = cv_meta.get("path_pdf")
                    if cv_pdf_file and cv_pdf_file.exists():
                        filename = cv_pdf_file.name
                        with open(cv_pdf_file, "rb") as attachment:
                            part = MIMEBase("application", "pdf")
                            part.set_payload(attachment.read())
                        encoders.encode_base64(part)
                        part.add_header("Content-Disposition", f"attachment; filename={filename}")
                        message.attach(part)
        
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, gmail_address, message.as_string())
        
        log.info(f"✓ HTML email briefing sent to {gmail_address}")
    except Exception as exc:
        log.warning(f"Email notification error: {exc}")


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

    # Load application generation sources
    profile = apply.load_profile()
    cv_master = apply.load_cv()
    cv_paths: list[dict] = []

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

    # LinkedIn authenticated scraper (Fix 3)
    linkedin_jobs = scrape_linkedin_playwright()
    all_jobs.extend(linkedin_jobs)
    if linkedin_jobs:
        sources_scanned += 1

    # Company career pages (very-high and high fit only)
    # Fix 2: Sia Partners / ServiceNow / Roche / Novartis use Playwright renderer
    for company in portals.get("tracked_companies", []):
        if company.get("fit") not in ("very-high", "high"):
            continue
        if company["name"] in PLAYWRIGHT_COMPANIES:
            all_jobs.extend(scrape_company_page_playwright(company))
        else:
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

    # ── Step 3: Pre-filter — nav links + engineering roles ──────────────────────
    to_score: list[dict] = []
    auto_skipped = 0
    for job in deduped:
        title = job.get("job_title", "")
        # Fix 1: discard items with no role signal in the title (nav/CTA noise)
        if not has_role_signal(title):
            log.debug(f"Auto-skip (no role signal): {title[:60]}")
            auto_skipped += 1
            continue

        # Pre-filter by high-level focus keywords before calling Claude
        if not has_scoring_keyword(title):
            log.info(f"Auto-skip (title focus): {title[:60]}")
            mark_tracked(sheet, job, today)
            auto_skipped += 1
            continue

        # Discard pure engineering roles before calling Claude (save tokens)
        if is_engineering_role(title):
            log.info(f"Auto-skip (engineering): {title[:60]}")
            mark_tracked(sheet, job, today)
            auto_skipped += 1
        else:
            to_score.append(job)
    log.info(f"To score: {len(to_score)} ({auto_skipped} auto-skipped)")

    # ── Step 4: Score with Claude API ───────────────────────────────────────────
    pipeline_jobs:  list[dict] = []   # score >= 3.5 → "pipeline" tab
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

        # Mark as tracked (dedup gate)
        mark_tracked(sheet, job, today)

        # Route by score
        if score >= 3.5:
            log.info(f"   PIPELINE ✓  score={score}  verdict={result.get('verdict')}")
            
            # Create readable folder name: YYYY-MM-DD_Job_Title
            def sanitize_for_folder(text: str, max_len: int = 30) -> str:
                safe = re.sub(r"[^A-Za-z0-9 _-]", "", text or "")
                safe = re.sub(r"[\s]+", "_", safe).strip("_")
                safe = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", safe)
                tokens = [token for token in safe.split("_") if token]
                # Fix doubled titles like AI_LeadAI_Lead -> AI_Lead
                if len(tokens) % 2 == 0 and len(tokens) >= 4:
                    half = len(tokens) // 2
                    a = [t.lower() for t in tokens[:half]]
                    b = [t.lower() for t in tokens[half:]]
                    if a == b:
                        tokens = tokens[:half]
                collapsed = []
                for token in tokens:
                    if not collapsed or token.lower() != collapsed[-1].lower():
                        collapsed.append(token)
                safe = "_".join(collapsed)
                return safe[:max_len] or "Unknown"
            
            job_title_clean = sanitize_for_folder(job.get("job_title", "Job"))
            folder_name = f"{today}_{job_title_clean}"
            
            append_pipeline(sheet, job, result, today, folder_name)
            pipeline_jobs.append({"job": job, "result": result})

            # Generate tailored application artifacts for pipeline roles
            job_id = apply.extract_job_id(job.get("url", ""))
            if job_id:
                try:
                    # Convert job dict field names for apply.py (job_scanner uses job_title and full_description)
                    job_for_apply = {
                        "title": job.get("job_title", ""),
                        "company": job.get("company", ""),
                        "description": job.get("full_description", job.get("description", "")),
                        "url": job.get("url", ""),
                    }
                    application_analysis = apply.score_and_extract_keywords(job_for_apply, profile, cv_master, claude)
                    tailored_cv = apply.generate_tailored_cv(cv_master, application_analysis.get("keywords", []), job.get("job_title", ""), job.get("company", ""), claude)
                    cover_letter = apply.generate_cover_letter(job_for_apply, profile, application_analysis.get("keywords", []), cv_master, claude)
                    
                    app_dir = apply.save_application(folder_name, job_for_apply, application_analysis, tailored_cv, cover_letter)
                    
                    # Build CV metadata for email attachment tracking
                    title_clean = sanitize_filename(job.get("job_title", "job"))
                    company_clean = sanitize_filename(job.get("company", "company"))
                    pdf_filename = f"CV_Enrique_{title_clean}_{company_clean}.pdf"
                    
                    cv_paths.append({
                        "path_pdf": app_dir / pdf_filename,
                        "path_md": app_dir / "cv.md",
                        "title": title_clean,
                        "company": company_clean,
                        "job_title": job.get("job_title", ""),
                    })
                    log.info(f"✓ Saved applications/{folder_name}/{pdf_filename}")

                    # Generate cover letter PDF (for email attachment)
                    cl_md_path = app_dir / "cover-letter.md"
                    cl_pdf_path = app_dir / f"CoverLetter_Enrique_{title_clean}_{company_clean}.pdf"
                    try:
                        if cl_md_path.exists():
                            with open(cl_md_path, "r") as f:
                                cl_md = f.read()
                            cl_paras = extract_cover_letter_body_paragraphs(cl_md)
                            role_title = job.get("job_title", "")
                            build_cover_letter(str(cl_pdf_path), role_title, cl_paras)
                            cv_paths.append({
                                "path_pdf": cl_pdf_path,
                                "title": title_clean,
                                "company": company_clean,
                                "job_title": job.get("job_title", ""),
                            })
                            log.info(f"✓ Saved applications/{folder_name}/{cl_pdf_path.name}")
                    except Exception as exc:
                        log.warning(f"Cover letter PDF generation failed: {exc}")
                except Exception as exc:
                    log.warning(f"Application generation failed for {job.get('job_title', 'Unknown')}: {exc}")
                    # Update Google Sheets to indicate failure
                    append_pipeline(sheet, job, result, today, f"FAILED_{folder_name}")
            else:
                log.warning(f"Skipping application generation for non-LinkedIn job URL: {job.get('url', '')}")
                append_pipeline(sheet, job, result, today, f"NON_LINKEDIN_{folder_name}")
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
    generate_pdf(pipeline_jobs, partial_fits, pdf_path, today, stats, claude)

    # ── Step 6: Send email briefing ─────────────────────────────────────────────
    send_email_briefing(pipeline_jobs, partial_fits, stats, today, pdf_path, cv_paths)

    # ── Summary ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Job Scanner — {today}")
    print(f"{'='*60}")
    print(f"Sources scanned : {sources_scanned}")
    print(f"Jobs fetched    : {total_fetched}")
    print(f"New (deduped)   : {len(deduped)}")
    print(f"Scored by Claude: {scored_count}")
    print(f"Pipeline (≥3.5) : {len(pipeline_jobs)}")
    print(f"Partial (3-3.9) : {len(partial_fits)}")
    print(f"PDF briefing    : {pdf_path}")
    print(f"{'='*60}\n")

    log.info("=== Job Scanner complete ===")


if __name__ == "__main__":
    main()
