# Career-Ops: Application Generation Mode (ATS Optimization)

**Purpose:** Generate tailored, ATS-friendly CV and cover letter for a specific job posting by analyzing the job description, extracting key requirements, and injecting them into your master CV and profile positioning.

**Source of Truth:**
- `cv.md` — Master experience narrative (never modified by this mode)
- `profile.yml` — Positioning, one-liner, core thesis, differentiators
- `applications/{job-id}/` — Output directory for tailored artifacts

---

## Workflow

### Step 1: Input — LinkedIn Job URL

```
Mode: application
Input: https://www.linkedin.com/jobs/view/[JOB_ID]/
Output: applications/[job-id]/
```

**Action:**
- Extract Job ID from URL
- Create directory: `applications/{job-id}/`
- Fetch LinkedIn job page (Playwright + li_at cookie)
- Extract job title, company, full job description

---

### Step 2: Score Fit (1–5 Scale)

**Source:** `profile.yml` positioning and target roles + candidate skills

**Scoring Logic:**
- **5.0** — Perfect role match (exact target role, regulated industry, right geography, seniority level)
- **4.5–4.9** — Strong fit, minor gap (location or one missing proof point)
- **4.0–4.4** — Good fit, skill gap is addressable
- **3.5–3.9** — Moderate fit, worth tailoring
- **< 3.5** — Skip (not worth effort)

**Output:** Log fit score + brief rationale to `applications/{job-id}/analysis.json`

---

### Step 3: Extract ATS Keywords (15–20)

**Method:** NLP-based keyword extraction using Claude + regex pattern matching

**Keywords to extract:**
- Role titles mentioned in JD (e.g., "transformation lead", "AI strategy")
- Technologies/frameworks (e.g., "Agile", "SAP", "Salesforce")
- Methodologies (e.g., "LEAN", "Six Sigma", "OKRs")
- Soft skills (e.g., "stakeholder management", "change management")
- Industry terms (e.g., "vendor management", "SaaS", "enterprise")
- Company-specific tools (e.g., "Jira", "Confluence", "Salesforce")

**Filtering:**
- Remove generic filler terms ("team player", "communication skills")
- Prioritize terms that appear in `profile.yml` positioning or `cv.md` already
- Rank by frequency and specificity

**Output:**
```json
{
  "job_title": "Digital Transformation Lead",
  "company": "Acme Inc",
  "keywords": [
    "digital transformation",
    "organizational change",
    "process improvement",
    "stakeholder alignment",
    "agile transformation",
    "LEAN",
    "enterprise architecture",
    "cross-functional leadership",
    "governance",
    "capability building",
    "vendor management",
    "SAP",
    "cloud migration",
    "IT strategy",
    "business case development"
  ],
  "fit_score": 4.2,
  "fit_rationale": "Strong domain match (transformation), slight gap on cloud/SAP exposure."
}
```

---

### Step 4: Generate Tailored CV

**Source:** `cv.md` (never modified; only reordering and emphasis)

**Process:**
1. **Parse** the master CV into sections (Summary, Experience, Education, Certifications, Skills)
2. **Reorder** experience bullets to front-load keywords matching the job
3. **Inject keywords** into the summary and each role (naturally, no keyword stuffing):
   - Rephrase without losing meaning
   - Prioritize keywords that fit your actual experience
   - Add specificity where the JD demands it (e.g., if JD emphasizes "vendor negotiations", highlight that from your experience)
4. **Emphasize skills** that match the JD while staying true to your actual background
5. **Output:** `applications/{job-id}/cv.md`

**Template:**

```markdown
# {Name} — {Profile Role}

**Location:** {location} | {citizenship}  
**Email:** {email} | **LinkedIn:** {linkedin} | **Website:** {website}

---

## Summary

{positioning.one_liner}

{Narrative that:
- Opens with the job's core need (e.g., "organizational readiness for transformation")
- Shows how your background directly addresses it
- Injects 3–5 high-value keywords naturally
- References proof points from profile.yml
}

---

## Experience

{For each role:
- Title and company
- Dates and location
- Bullets reordered to front-load keyword matches
- 2–3 bullets injected with job-specific keywords while staying true to cv.md
}

---

## Skills

{Reorder skills to match JD priorities; add context (e.g., "LEAN IT Foundation", not generic "Lean")}

---

## Education & Certifications

{Unchanged from cv.md}
```

---

### Step 5: Generate Tailored Cover Letter

**Source:** `profile.yml` positioning + tailored CV context

**Structure:**
1. **Opening (1 para):** Role title + company + why you're applying (specific to the JD, not generic)
2. **Proof points (2–3 paras):** Select 3–4 experiences that directly map to JD requirements; use job keywords naturally
3. **Why now (1 para):** Alignment between your positioning and their current challenge
4. **Close:** Call to action

**Template:**

```markdown
# Cover Letter — {Job Title} at {Company}

Dear {Hiring Manager / Hiring Team},

I'm writing to apply for the {Job Title} role at {Company}. Your mandate to {extract key challenge from JD} aligns with the exact intersection where I've spent the last {N} years: building organizations that can actually execute transformation, not just plan it.

{Proof Point 1: Connect one role/achievement from cv.md + JD keywords}

{Proof Point 2: Connect another achievement}

{Proof Point 3: Why this role, this company, this moment}

I'd welcome the chance to discuss how my background in {positioning.primary} can help {Company} navigate {specific challenge from JD}.

Best regards,  
{Name}
```

**Tone:** Professional, specific to the job, not templated. Personalization matters.

---

### Step 6: Save Artifacts

**Output structure:**
```
applications/{job-id}/
├── cv.md                    # Tailored CV
├── cover-letter.md          # Tailored cover letter
├── analysis.json            # Fit score, keywords, rationale
└── README.md                # Job details + submission checklist
```

**README template:**
```markdown
# Application: {Job Title} at {Company}

- **Posted:** {date}
- **Link:** {LinkedIn URL}
- **Fit Score:** {1–5}
- **Keywords Matched:** {15–20 keywords}

## Submission Checklist
- [ ] Review cv.md and cover-letter.md
- [ ] Verify keyword injection doesn't distort your message
- [ ] Check application portal rules (CV format, cover letter length, etc)
- [ ] Submit via LinkedIn/ATS
- [ ] Log submission to Google Sheets "tracked" tab
- [ ] Follow up in 1 week if no response

## Notes
{Any custom context for this application}
```

---

## Implementation Details

### Dependencies
- `Playwright` (already in job_scanner.py) — fetch LinkedIn job pages
- `Claude API` — keyword extraction + fit scoring
- `BeautifulSoup` — LinkedIn JD parsing
- `YAML` (profile.yml reading)
- `Markdown` (CV generation)

### Key Functions

```python
def extract_job_details(url: str) -> dict:
    """Fetch LinkedIn job page and extract JD, title, company."""
    # Playwright + CSS selectors to extract:
    # - job title
    # - company
    # - full job description
    # Return structured dict

def score_job_fit(jd: str, profile: dict) -> float:
    """Score fit based on JD + candidate positioning."""
    # Use Claude to evaluate fit 1–5
    # Return score + rationale

def extract_keywords(jd: str, cv_text: str, profile_text: str) -> list:
    """Extract 15–20 relevant ATS keywords from JD."""
    # Claude-powered extraction + ranking
    # Filter for relevance to candidate's background
    # Return sorted list

def generate_tailored_cv(cv_master: str, keywords: list, job_title: str) -> str:
    """Generate ATS-optimized CV by injecting keywords."""
    # Parse cv_master into sections
    # Reorder bullets to prioritize keywords
    # Generate Markdown with injected keywords
    # Return tailored CV text

def generate_cover_letter(profile: dict, cv_tailored: str, jd: str, job_title: str) -> str:
    """Generate personalized cover letter."""
    # Use Claude to write natural, personalized letter
    # Map CV proof points to JD requirements
    # Return cover letter Markdown
```

### Invocation

```bash
# Single job application
python3 -m modes.application --url "https://www.linkedin.com/jobs/view/[ID]"

# Batch: score all jobs in Google Sheets pipeline
python3 -m modes.application --batch --min-fit 3.5
```

---

## Guardrails

1. **Never distort your narrative:** Keywords are injected to highlight existing strengths, not fabricate them.
2. **CV source of truth is inviolate:** `cv.md` is never rewritten; only `applications/{job-id}/cv.md` changes.
3. **Fit threshold:** Don't generate applications for jobs scoring < 3.5 (time waste).
4. **Keyword stuffing boundaries:** Max 1 keyword injection per bullet point; maintain readability.
5. **Cover letter authenticity:** Each cover letter is unique, not a template. Close only when you genuinely want the role.

---

## Example Flow

**Input:** LinkedIn job URL  
**Job:** "Digital Transformation Lead @ Siemens"

**Step 1–2:** Extract JD; score fit = 4.3 ✅

**Step 3:** Extract keywords  
→ digital transformation, organizational change, LEAN, cross-functional leadership, vendor management, enterprise architecture, governance, change management, business case development, enterprise systems, Agile, CI/CD, cloud migration, capability building, process improvement

**Step 4:** Generate CV (`applications/siemens-dt-lead/cv.md`)  
→ Reorder experience to lead with transformation projects + governance expertise  
→ Inject keywords: "25 transformation projects pilot→steady state" becomes "25 transformation projects (organizational change + governance) from pilot to steady state in regulated energy sector"  
→ Skills section reordered: LEAN first, enterprise architecture highlighted, governance emphasized

**Step 5:** Generate cover letter  
→ Open: "Your mandate to scale transformation across manufacturing operations aligns with my decade in organizational change and regulated-sector execution."  
→ Proof points from cv.md: MSD adoption roadmap, Quint Group 25-project portfolio  
→ Close: "I'd welcome discussing how my background in LEAN + enterprise transformation can help Siemens accelerate adoption across your division."

**Step 6:** Save  
```
applications/siemens-dt-lead/
├── cv.md
├── cover-letter.md
├── analysis.json
└── README.md
```

Submit + track in Google Sheets.

---

## Future Enhancements

- **Resume screening simulation:** Run both CV and cover letter through an ATS parser (e.g., Workable API) before finalizing
- **A/B testing:** Generate 2–3 keyword-injection variants, rate for readability
- **Follow-up automation:** Trigger reminders based on application date; log response rates by keyword frequency
- **Salary extraction:** Pull salary info from JD Paragraph where available; store in analysis.json
- **Interview prep:** Generate interview briefing with company context, common questions for the role, etc.
