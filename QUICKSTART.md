# Career-Ops: 60-Second Application Generation

From job email → tailored application ready to submit.

---

## The Workflow

### 1. Daily Job Scan (Automated)
```bash
# Runs daily via cron
python3 job_scanner.py
```
**Output:** 
- Email with pipeline roles (fit score ≥ 3.5)
- Roles ranked by fit score
- Direct LinkedIn job links

---

### 2. You Find a Role You Like
- Open the email
- Read the job title, company, fit score
- Copy the **LinkedIn job URL**

Example:
```
https://www.linkedin.com/jobs/view/4383794205/
```

---

### 3. Generate Tailored Application (60 seconds)
```bash
python3 apply.py https://www.linkedin.com/jobs/view/4383794205/
```

**What happens:**
1. Fetches job posting from LinkedIn (via Playwright + auth)
2. Scores fit (1–5) using Claude + profile.yml
3. Extracts 15–20 ATS keywords from job description
4. Injects keywords into master cv.md
5. Generates personalized cover letter
6. Saves everything to `applications/{job-id}/`

**Output:**
```
applications/4383794205/
├── cv.md                    # Tailored CV (keywords injected)
├── cover-letter.md          # Personalized cover letter
├── analysis.json            # Fit score, keywords, rationale
└── README.md                # Submission checklist + notes
```

---

### 4. Review & Submit (5 minutes)

**Step 1:** Read the tailored artifacts
```bash
open applications/4383794205/cv.md
open applications/4383794205/cover-letter.md
```

**Step 2:** Verify quality
- Keywords don't distort your narrative? ✓
- Cover letter is personalized (not templated)? ✓
- Fit score reasonable? ✓

**Step 3:** Check application rules
- Does the company want PDF or LinkedIn apply? 
- Any specific format rules?

**Step 4:** Submit
- Upload CV + cover letter to ATS or LinkedIn
- Or use LinkedIn "Easy Apply" if available

**Step 5:** Track
- Add to Google Sheets "tracked" tab with submission date
- Set phone reminder for 1-week follow-up

---

## Examples

### Example 1: Digital Transformation Lead @ Acme
```bash
$ python3 apply.py https://www.linkedin.com/jobs/view/4383794205/

=== Career-Ops ATS Application Generator ===
Job ID: 4383794205
Loading profile and master CV...
Fetching LinkedIn job posting...
Title: Digital Transformation Lead
Company: Acme Inc
Scoring fit and extracting ATS keywords...
Fit Score: 4.3/5.0
Keywords: digital transformation, organizational change, LEAN, ...
Generating tailored CV with keyword injection...
Generating personalized cover letter...
Saving application artifacts...
✓ Application ready at: applications/4383794205/
Next: Review the files and submit via LinkedIn/ATS
```

**Result:**
- `cv.md`: "25 transformation projects (organizational change + governance)" ← keywords injected
- `cover-letter.md`: "Your mandate to scale transformation aligns with my decade in org change..."
- `analysis.json`: `{"fit_score": 4.3, "keywords": [...], "fit_rationale": "..."}`
- `README.md`: Submission checklist

---

### Example 2: Fit Too Low (Skipped)
```bash
$ python3 apply.py https://www.linkedin.com/jobs/view/4380000000/

Loading profile and master CV...
Fetching LinkedIn job posting...
Title: Senior Python ML Engineer
Company: ML Startup
Scoring fit and extracting ATS keywords...
Fit Score: 2.1/5.0

⚠ Fit score 2.1 below 3.5 threshold — not worth tailoring
```

**Saved effort:** No wasted CV/cover letter generation for poor matches.

---

## Guardrails

### ✓ What This Does Well
- Finds overlaps between your background and the job
- Injects keywords naturally (no keyword stuffing)
- Generates cover letters that feel personalized + authentic
- Skips low-fit roles automatically (3.5 threshold)

### ✗ What This Does NOT Do
- Apply to the ATS automatically (you always submit manually)
- Fabricate skills or experience you don't have
- Generate robotic, templated cover letters
- Track interview outcomes (you do that manually in Google Sheets)

### Best Practices
1. **Always review before submitting** — AI-generated text isn't perfect
2. **Edit if needed** — Personalize further if the cover letter feels generic
3. **Track submissions** — Log to Google Sheets with submission date
4. **Follow up in 1 week** — If no response, send a brief follow-up note
5. **Save all artifacts** — Keep applications/ for future reference

---

## Troubleshooting

### "LINKEDIN_LI_AT not set"
Your LinkedIn session cookie is missing. Set it:
```bash
# 1. Open LinkedIn in browser
# 2. Open DevTools → Application → Cookies → linkedin.com
# 3. Find "li_at" cookie value
# 4. Add to .env:
echo "LINKEDIN_LI_AT=<paste-cookie-value>" >> .env
```

### "Bad JSON from Claude"
Claude API returned malformed response. This is rare. Try again:
```bash
python3 apply.py https://www.linkedin.com/jobs/view/XXXXX/
```

### "Fetch failed"
LinkedIn page didn't load. Check:
1. URL is valid LinkedIn job URL
2. Job is publicly posted (not recruitment agency spam)
3. Your li_at cookie isn't expired (refresh if needed)

### Application threshold error (fit score < 3.5)
The job isn't a good match. Consider:
1. Was the fit score too harsh? You can manually adjust in analysis.json
2. Is the role on your target list? Check profile.yml positioning
3. Skip it and look at the next pipeline role

---

## Advanced: Batch Mode (Coming Soon)

Generate applications for ALL pipeline jobs from Google Sheets:
```bash
python3 apply.py --batch --min-fit 3.5
```

This will:
1. Fetch all jobs from Google Sheets "pipeline" tab (fit ≥ 3.5)
2. Generate CV + cover letter for each
3. Save to `applications/{job-id}/` directories
4. Mark as "generated" in Google Sheets

---

## Integration with job_scanner.py

### Daily Workflow (Recommended)
```bash
# 1. Morning: Run scanner (automated or manual)
python3 job_scanner.py

# 2. Check email for pipeline roles

# 3. For each role you like:
python3 apply.py https://www.linkedin.com/jobs/view/XXXXX/

# 4. Review + submit within 24 hours
```

### Weekly Batch (Alternative)
```bash
# End of week: generate all pipeline applications
python3 apply.py --batch

# Review all generated applications
ls -la applications/*/

# Submit 3–5 of the best fits
```

---

## Metrics to Track

In Google Sheets "tracking" tab, log:
- Date applied
- Job title + company
- Fit score
- Application status (submitted, hold, declined)
- Interview invitations (Y/N)
- Interview date (if applicable)

This helps identify which roles/companies respond best to your profile.

---

## Quick Reference

| Command | Purpose |
|---------|---------|
| `python3 job_scanner.py` | Daily job scan → email briefing |
| `python3 apply.py <url>` | Generate application for 1 job |
| `python3 apply.py --batch` | Generate applications for top 10 pipeline roles |
| `ls applications/` | View all generated applications |
| `open applications/4383794205/cv.md` | Review tailored CV |
| `open applications/4383794205/README.md` | View submission checklist |

---

## Next Steps

1. **Today:** Run `python3 job_scanner.py`, get email with pipeline roles
2. **Find 1 role:** Copy LinkedIn URL from email
3. **Generate:** `python3 apply.py <url>` → wait 60 seconds
4. **Review:** Check cv.md, cover-letter.md, README.md
5. **Submit:** Upload to ATS or LinkedIn
6. **Track:** Log to Google Sheets with submission date
7. **Follow up:** Reminder in 1 week if no response

---

**Questions?** Check [modes/pdf.md](modes/pdf.md) for detailed workflow specs.

**Issues?** Check job_scanner.py logs: `tail -f output/scanner.log`
