# QC Degree Planner

Semester-by-semester degree planner for Queens College majors. Pick a major, get a proposed Fall 1
(grey cards), edit/approve it, get Spring 1 suggested from what Fall 1 unlocked, and so on — drawn as a
layered DAG with prerequisite edges.

```
python backend/scrape.py        # once: programs + courses from the QC catalog API -> frontend/public/data/*.json
python backend/prereqs.py       # once: prereq edges from the CUNYfirst requirement groups + catalog text
python backend/sections.py      # once: real class sections (days/times/instructor/status) from CUNYfirst class search
python backend/server.py        # suggestion + advisor-chat API on :8000   (set GEMINI_API_KEY for Gemini 3.7 picks + chat; otherwise rule-based, chat off)
cd frontend && npm install && npm run dev      # http://localhost:5173  (proxies /api to :8000)
python backend/test_plan.py     # self-check of the planning logic
```

## Setup & testing (teammates)

Needs **Python 3.10+** (`python -m pip install -r backend/requirements.txt` for DegreeWorks PDF import) and **Node 20+**. The catalog data in
`frontend/public/data/` is committed, so skip the scrape/prereq steps unless you're refreshing it.

```
git clone <repo-url> && cd hack
python -m pip install -r backend/requirements.txt  # needed for DegreeWorks PDF import
python backend/test_plan.py          # 1. self-check: should print "... OK" lines and exit 0
python backend/server.py             # 2. API on http://localhost:8000 (leave running)
cd frontend && npm install && npm run dev   # 3. UI on http://localhost:5173, in a second terminal
```

Manual smoke test in the browser: pick **Computer Science BS** → the Fall 1 proposal should include ENGL 110 and
CSCI 111 at 15–20 credits → **Approve** → Spring 1 should suggest CSCI 211/212 (unlocked by CSCI 111). Add a
course whose prereqs aren't met and confirm it turns red and blocks Approve.

Optional: `set GEMINI_API_KEY=...` (Windows) / `export GEMINI_API_KEY=...` before step 2 for AI-ordered
semesters and the **Advisor** chatbot (header button; `POST /api/chat`, model `gemini-3.7-flash`, grounded in the approved plan,
major progress and the eligible list for the next term). Without a key the rule-based picker is used, the response shows
`"source": "heuristic"`, and the chat replies that the key is missing. Never commit the key.
`test_plan.py` always runs rule-based.

Refresh `sections.json` once a term, when the registrar publishes the next schedule (`sections_meta.json`
records when it was last scraped, and the UI shows that date rather than implying the seat status is live).

## How a semester is suggested

1. `server.py` computes the **eligible** set: not taken, prerequisites met by approved terms (placement assumed
   for MATH ≤ 122; "Prereq. or coreq." courses may pair with a same-term course), offered that term, and still
   needed by an unmet major rule or an open Pathways slot (or a major/free elective).
2. Each candidate carries *why* (e.g. "Major Core: required", "Pathways: Life & Physical Sciences") and what it
   **unlocks** (CSCI 111 → CSCI 211, 212, 240).
3. Pinned and queued courses that are eligible are locked into the term first. With `GEMINI_API_KEY`, Gemini
   orders the rest **from that list only** and writes a one-line reason per course; every pick (Gemini's or the
   rule-based picker's) goes through the same guards — ≥5 courses, 15–20 credits, coreq partner present, one course
   per Pathways slot, ≤3 required-core per term — and the rule-based phases top up anything Gemini left short.
   Responses are cached per (program, approved terms, term, locked courses); **Regenerate** bypasses the cache.
4. The student removes/adds courses — any catalog course can be added; a course whose prerequisites aren't met by an
   earlier term turns red (none met) or yellow (some met) and blocks Approve, duplicates warn, and a 200+ course with
   no prerequisite source shows a yellow `!` — then approves; progress toward the major and all Pathways slots updates.
   Pathways slots are assigned by maximum matching (one course, one slot; a major course listed under both Core and
   College Option goes to College Option), and Writing Intensive suggestions prefer the lowest-level W course rather
   than a prerequisite chain.

## Data

- Programs/courses: `app.coursedog.com/api/v1/cm/qns01/...` (the catalog site is Coursedog; its HTML has no data).
- Prerequisites (`backend/prereqs.py`), highest priority first: **CUNYfirst requirement groups** (official requisite
  text, fetched per course from the catalog API — 1,054 groups), the catalog's requisite field, then course
  descriptions. Every prerequisite records its source; 200+ courses with no source are marked "unverified" in the
  UI. With `GEMINI_API_KEY`, Gemini re-parses the official text and its parse wins.
  The 2020-21 Bulletin PDF was removed as a source — it supplied 36 of 1,986 prereqs, was the only reason this
  project needed `pdftotext`, and contradicted the live catalog (see the `prereqs.py` docstring).
- Sections (`backend/sections.py`): `globalsearch.cuny.edu` (public CUNYfirst class search, institution `QNS01`) —
  real days, times, room, instructor, instruction mode and open/closed status per section. **This is what makes
  `offered()` meaningful:** the catalog's own `courseTypicallyOffered` field is the literal string "Fall, Spring"
  for 3,611 of 3,834 courses, so it could not distinguish a course that runs every term from one last taught in
  2019. A course with no section in any scraped term is no longer suggested.
- The approved plan is re-validated on every request (`validate` in `server.py`); violations render red.
- Pathways course list: `backend/data/gened.csv` (QC approved Gen Ed courses); rules from qc.cuny.edu/academics/gened.
