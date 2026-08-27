"""Pull real Queens College class sections (days, times, room, instructor, mode, status) from the
public CUNYfirst class search into static JSON.

    python backend/sections.py                  # all terms -> frontend/public/data/sections.json
    python backend/sections.py --term 1269 --subject CMSC --dry    # spike: print, write nothing

Why this exists: the Coursedog catalog's `courseTypicallyOffered` is the literal string "Fall, Spring"
for 3,611 of 3,834 courses (94%), so `offered()` in server.py could not actually tell whether a course
runs. A course that has not been taught since 2019 looked identical to CSCI 111. These section lists are
the ground truth: if a course has no section in any scraped term, it is not really offered.

globalsearch.cuny.edu is a three-step JSP wizard, no login and no CSRF token:
  1. GET  search.jsp                                  -> session cookie
  2. POST inst_selection=QNS01 & term_value=<id>      -> the criteria form
  3. POST subject_name=<subj> & the criteria fields   -> the result table

Three traps, found the hard way:
  * The meeting-time operator fields are REQUIRED (omitting them 500s) but an operator with empty text
    matches nothing. GE 12:00am / LE 11:59pm is the "no filter" spelling.
  * The search FILTER uses CUNYfirst subject codes (CMSC, UBST) while the catalog uses its own
    (CSCI, URBST). The codes *rendered in the results* are the catalog's, so we join on those and never
    need a crosswalk -- we just iterate every subject the form offers and read back whatever it returns.
  * The status icon's accessibility `alt` text is misleading: even status_waiting.gif can say
    alt="Open". The actual state is in `title` (Open / Closed / Wait), with the icon filename as a
    fallback. Never infer registration status from `alt`.

Stdlib only.
"""
import argparse, html, http.cookiejar, json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

BASE = "https://globalsearch.cuny.edu/CFGlobalSearchTool"
INST = "QNS01"
INST_NAME = "Queens College"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "data"

# The terms the tool still serves. Seasons map to (newest first) so `offered()` prefers live data and
# falls back to the same season a year earlier for terms further out than the registrar has published.
TERMS = {"1269": "2026 Fall Term", "1266": "2026 Summer Term", "1262": "2026 Spring Term"}
SEASON = {"Fall": ("1269",), "Spring": ("1262",), "Summer": ("1266",), "Winter": ()}

DAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
# result-page markers, matched in document order: a course heading, or one table cell
HEADING = re.compile(r"<span>&nbsp;<a id='imageDivLink\d+'.*?</a>&nbsp;(.*?)</span>", re.S)
CELL = re.compile(r'<td[^>]*data-label="([^"]*)"[^>]*>(.*?)</td>', re.S)
TIME = re.compile(r"([A-Za-z]{2,10}?)\s+(\d{1,2}):(\d{2})([AP]M)\s*-\s*(\d{1,2}):(\d{2})([AP]M)")
COUNT = re.compile(r"(\d+) class section\(s\) found")
STATUS_NAMES = {
    "open": "Open",
    "closed": "Closed",
    "wait": "Wait List",
    "waiting": "Wait List",
    "wait list": "Wait List",
}


def text(s):
    """Strip tags and entities from a table cell."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def minutes(h, m, ampm):
    """'1:40PM' -> 820 (minutes past midnight). Integers overlap-test in one comparison downstream."""
    h = int(h) % 12 + (12 if ampm.upper() == "PM" else 0)
    return h * 60 + int(m)


def parse_days(s):
    """'TuTh' -> 'TuTh'; tolerates 'Mo We Fr' and drops anything unrecognised (TBA, online)."""
    return "".join(d for d in DAYS if d in s)


def parse_meetings(cell):
    """'TuTh 1:40PM - 2:30PM' -> [('TuTh', 820, 870)]. A cell may hold several meeting lines."""
    out = []
    for days, h1, m1, ap1, h2, m2, ap2 in TIME.findall(cell):
        d = parse_days(days)
        if d:
            out.append((d, minutes(h1, m1, ap1), minutes(h2, m2, ap2)))
    return out


def parse_status(cell):
    """Return Open / Closed / Wait List from a Global Search Status cell.

    Do NOT trust the image's ``alt`` attribute. CUNY currently renders waitlisted rows like:
        <img src="images/status_waiting.gif" alt="Open" title="Wait">
    so reading ``alt`` silently turns every waitlisted section into Open. The title is the semantic
    state used by the page; the icon filename is a defensive fallback. Unknown markup stays unknown.
    """
    cell = cell or ""
    title = re.search(r"\btitle\s*=\s*['\"]([^'\"]+)['\"]", cell, re.I)
    if title:
        value = html.unescape(title.group(1)).strip().lower()
        if value in STATUS_NAMES:
            return STATUS_NAMES[value]

    icon = re.search(r"status_(open|closed|waiting)\.gif", cell, re.I)
    if icon:
        return STATUS_NAMES[icon.group(1).lower()]
    return ""


class Search:
    """One cookie session, reused across subjects within a term (3 requests -> 1 per extra subject)."""

    def __init__(self, term, term_name):
        self.term, self.term_name = term, term_name
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._get(f"{BASE}/search.jsp")
        self._post([("selectedInstName", f"{INST_NAME};"), ("inst_selection", INST),
                    ("selectedTermName", term_name), ("term_value", term), ("next_btn", "Next")],
                   f"{BASE}/search.jsp")

    def _get(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        return self.op.open(req, timeout=60).read().decode("utf8", "ignore")

    def _post(self, pairs, referer):
        # field ORDER matters to this JSP; keep it exactly as the form declares it
        req = urllib.request.Request(
            f"{BASE}/CFSearchToolController", data=urllib.parse.urlencode(pairs).encode(),
            headers={"User-Agent": UA, "Referer": referer, "Origin": "https://globalsearch.cuny.edu",
                     "Content-Type": "application/x-www-form-urlencoded"})
        return self.op.open(req, timeout=180).read().decode("utf8", "ignore")

    def subject(self, subj, career="UGRD"):
        return self._post([
            ("selectedSubjectName", subj), ("subject_name", subj),
            ("selectedCCareerName", "Undergraduate"), ("courseCareer", career),
            ("selectedCAttrName", ""), ("courseAttr", ""),
            ("selectedCAttrVName", ""), ("courseAttValue", ""),
            ("selectedReqDName", ""), ("reqDesignation", ""),
            ("selectedSessionName", ""), ("class_session", ""), ("selectedModeInsName", ""),
            # required, and an operator with empty text matches nothing -- these bounds mean "any time"
            ("meetingStart", "GE"), ("selectedMeetingStartName", ""),
            ("meetingStartText", "12:00am"), ("AndMeetingStartText", ""),
            ("meetingEnd", "LE"), ("selectedMeetingEndName", ""),
            ("meetingEndText", "11:59pm"), ("AndMeetingEndText", ""),
            ("daysOfWeek", "I"), ("selectedDaysOfWeekName", ""),
            ("instructor", "B"), ("selectedInstructorName", ""), ("instructorName", ""),
            ("search_btn_search", "Search"),
        ], f"{BASE}/CFSearchToolController")


def subjects(page):
    """The subject codes the criteria form offers (CUNYfirst codes -- only used as search filters)."""
    m = re.search(r'<select[^>]*name="subject_name"[^>]*>(.*?)</select>', page, re.S)
    return [v for v, _ in re.findall(r"<option[^>]*value='([^']*)'[^>]*>([^<]*)", m.group(1)) if v]


def parse(page):
    """-> {course code: [section dict]}. Walks headings and cells in document order; each heading
    ('CSCI 111 - Intro Algorithmic Problem Solv') owns the 9-column rows that follow it."""
    out, code = {}, None
    marks = sorted([(m.start(), "h", m.group(1)) for m in HEADING.finditer(page)] +
                   [(m.start(), "c", (m.group(1), m.group(2))) for m in CELL.finditer(page)])
    row = []
    for _, kind, val in marks:
        if kind == "h":
            head = text(val)
            m = re.match(r"([A-Z]{2,5})\s+(\w+)\s*-", head)
            code, row = (f"{m.group(1)} {m.group(2)}" if m else None), []
            continue
        if code is None:
            continue
        label, cell = val
        row.append((label, cell))
        if label != "Course Topic":                       # last column of a row
            continue
        cells = dict(row)
        row = []
        raw = text(cells.get("DaysAndTimes", ""))
        meetings = parse_meetings(raw)
        sec = text(cells.get("Section", ""))
        out.setdefault(code, []).append({
            "sec": sec.split("-")[0].strip(),
            "component": (sec.split("-")[1].split()[0] if "-" in sec else ""),   # LEC / LAB / REC
            "days": meetings[0][0] if meetings else "",
            "start": meetings[0][1] if meetings else None,
            "end": meetings[0][2] if meetings else None,
            "extra": [{"days": d, "start": s, "end": e} for d, s, e in meetings[1:]],
            "room": text(cells.get("Room", "")),
            "instr": text(cells.get("Instructor", "")),
            "mode": text(cells.get("Instruction Mode", "")),
            "status": parse_status(cells.get("Status", "")),
            "raw": "" if meetings else raw,                # keep "TBA" etc. so the UI can say so
        })
    return out


def scrape_term(term, name, only=None, verbose=True):
    s = Search(term, name)
    subs = only or subjects(s._post(
        [("selectedInstName", f"{INST_NAME};"), ("inst_selection", INST),
         ("selectedTermName", name), ("term_value", term), ("next_btn", "Next")],
        f"{BASE}/search.jsp"))
    found, total = {}, 0
    for i, sub in enumerate(subs, 1):
        for attempt in range(3):
            try:
                page = s.subject(sub)
                break
            except Exception as e:                        # ponytail: transient JSP 500s -> retry, then skip
                print(f"    {sub}: {e} (retry {attempt + 1})", file=sys.stderr)
                time.sleep(2 * (attempt + 1))
                s = Search(term, name)
        else:
            continue
        got = parse(page)
        n = sum(len(v) for v in got.values())
        total += n
        for k, v in got.items():
            found.setdefault(k, []).extend(v)
        if verbose:
            claimed = COUNT.search(page)
            flag = "" if not claimed or int(claimed.group(1)) == n else f"  !! page says {claimed.group(1)}"
            print(f"  [{i:2d}/{len(subs)}] {sub:6s} {len(got):3d} courses {n:4d} sections{flag}")
        time.sleep(0.3)
    return found, total


def status_counts(hit):
    """Small scrape-health signal stored in metadata; makes an all-Open parser regression obvious."""
    out = {"Open": 0, "Closed": 0, "Wait List": 0, "Unknown": 0}
    for secs in hit.values():
        for sec in secs:
            status = sec.get("status") or "Unknown"
            out[status if status in out else "Unknown"] += 1
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--term", action="append", help="term id (default: all)")
    ap.add_argument("--subject", action="append", help="CUNYfirst subject filter code, e.g. CMSC")
    ap.add_argument("--dry", action="store_true", help="print, write nothing")
    a = ap.parse_args()

    courses = json.loads((OUT / "courses.json").read_text(encoding="utf8"))
    by_code = {c["code"]: c["id"] for c in courses}

    out, meta = {}, {}
    for term in (a.term or list(TERMS)):
        print(f"{term} {TERMS[term]}...")
        found, total = scrape_term(term, TERMS[term], a.subject)
        hit = {by_code[k]: v for k, v in found.items() if k in by_code}
        missed = sorted(k for k in found if k not in by_code)
        counts = status_counts(hit)
        out[term] = hit
        meta[term] = {"name": TERMS[term], "courses": len(hit), "sections": total,
                      "unmatched_codes": len(missed), "statuses": counts}
        print(f"  -> {len(found)} distinct courses, {total} sections; "
              f"{len(hit)} matched a catalog course, {len(missed)} codes unmatched {missed[:8]}")
        print(f"     status: Open {counts['Open']}, Closed {counts['Closed']}, "
              f"Wait List {counts['Wait List']}, Unknown {counts['Unknown']}")

    if a.dry:
        for term, hit in out.items():
            for cid, secs in list(hit.items())[:3]:
                code = next(c["code"] for c in courses if c["id"] == cid)
                print(f"\n{code}:")
                for s in secs[:6]:
                    when = f"{s['start']}-{s['end']}" if s["start"] is not None else (s["raw"] or "TBA")
                    print(f"   {s['sec']:5s} {s['component']:4s} {s['days']:8s} "
                          f"{when:14s} {s['status']:10s} {s['instr']}")
        sys.exit(0)

    (OUT / "sections.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf8")
    (OUT / "sections_meta.json").write_text(json.dumps(
        {"scraped": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "source": BASE, "season": SEASON, "terms": meta},
        ensure_ascii=False, indent=1), encoding="utf8")
    covered = {cid for hit in out.values() for cid in hit}
    print(f"\nwrote {len(covered)} of {len(courses)} catalog courses with a real section -> {OUT / 'sections.json'}")
