# Daily Job Scanner Agent
# Schedule: every day at 07:00
# To activate: /login → /schedule

## Trigger
Daily at 07:00 local time.

## What this agent does

### Step 1 — Fetch job listings
Scrape the following sources for new postings matching AI transformation / digital strategy roles:

**LinkedIn:**
```
https://www.linkedin.com/jobs/search/?keywords=AI+transformation+consultant&location=Europe&f_WT=2
```
Also run secondary queries from portals.yml:
- "digital transformation consultant Prague"
- "AI strategy consultant Europe"
- "AI enablement lead Europe"
- "head of AI transformation"

**Wellfound:** https://wellfound.com/jobs — Business/Strategy filter, Europe

**Workable:** https://jobs.workable.com — AI / Strategy / Consulting, Europe

**Company pages** (from portals.yml tracked_companies, fit: very-high and high only):
- https://rfstrategy.com/careers
- https://www.sia-partners.com/en/careers
- https://www.wavestone.com/en/join-us/
- https://www.kearney.com/careers
- https://careers.servicenow.com
- https://careers.roche.com
- https://www.novartis.com/careers
- https://www2.deloitte.com/pt/en/pages/careers

**Extract per listing:** job_title, company, url, date_posted

---

### Step 2 — Deduplicate against Google Sheets
Search the "tracked" tab for existing URL.
- If URL already exists → skip entirely.
- If URL is new → proceed to Step 3.

---

### Step 3 — Score with Claude API
POST to `https://api.anthropic.com/v1/messages`

**System prompt:**
```
You are a job fit evaluator for a specific candidate profile.

Candidate: Enrique Wood Rivero
Primary positioning: AI Transformation Lead / Digital Strategy — business side
Key proof points:
- Production AI agent systems (competitor intel, content automation, market research) — deployed in code, 24/7
- Global adoption roadmap at MSD (multinational pharma)
- Obeya facilitation between engineering teams — accelerated cross-functional decisions
- 25 transformation projects pilot→steady state at Quint Group (regulated energy sector)
- AI Foundation Sprint methodology: process mapping, SSOT, data governance before AI

Fit signals (positive): business-side AI, org change, LEAN/ITIL/governance, consulting/advisory, cross-functional stakeholder management, regulated industry (pharma, energy, finance), Prague or Lisbon or remote Europe
Fit signals (negative): deep ML/Python engineering, no stakeholder interaction, pure data science, STEM hard filter

Target compensation: 65K–85K EUR gross/year
Location: Prague (current) | Lisbon (preferred relocation) | Remote Europe

Evaluate the job posting provided. Return ONLY valid JSON, no prose:
{
  "score": <float 1.0–5.0>,
  "fit_pct": <integer 0–100>,
  "salary_ask": "<string or null>",
  "verdict": "<apply|hold|skip>",
  "why": "<2 sentence max rationale>"
}

Scoring guide:
5.0 = perfect title + org change + regulated + right location
4.0–4.9 = strong fit, minor gap (location or one missing signal)
3.0–3.9 = partial fit, worth logging for review
< 3.0 = skip
```

**User message:** Full job description text

---

### Step 4 — Route by score

**If score >= 4.0:**
Append to Google Sheets tab "pipeline":
| date | job_title | company | url | score | fit_pct | salary_ask | verdict | why |

**If score < 4.0:**
Append to Google Sheets tab "skipped":
| date | job_title | company | url | score | verdict | why |

---

## Notes
- Avoid adding the same URL twice (dedup in Step 2 is the gate)
- If a page returns 403/blocked, log the source name and skip gracefully
- Lisbon/Portugal roles: add +0.5 to score before routing decision (per portals.yml agent_notes)
- Roles that prohibit independent consulting: flag in the "why" field, do not auto-skip
- Engineering-only roles (ML Engineer, Data Scientist, Python Dev): auto-skip before calling Claude API — save tokens
