"""Semester suggestion API. Stdlib only.

    python backend/server.py            # http://localhost:8000

POST /api/suggest  {"program": "CSCI-BS", "terms": [[courseId...]...], "term": "Fall"|"Spring"|"Summer"|"Winter",
                    "pins": [courseId...], "queue": [courseId...], "fresh": bool}
  -> {"suggested": [{"id","reason","unlocks":[ids]}], "candidates": [...same...], "progress": {...}, "source": "gemini"|"heuristic"}

The eligible set is computed here (prereqs met, not taken, offered that term, still needed by the major or
Pathways). Pinned/queued courses that are eligible are locked into the term first; Gemini then chooses the rest from
the eligible set, and its picks go through the same guards as the rule-based picker (credit cap, subject cap, coreq
partner, one course per Pathways slot). Responses are cached per input; "fresh" bypasses the cache (Regenerate).
"""
import csv, json, os, re, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / "frontend" / "public" / "data"
MODEL = "gemini-3.6-flash"
TARGET_CREDITS, MAX_CREDITS, MIN_COURSES = 15, 20, 5   # aim for ~15 cr and >=5 courses, never above 20 cr

courses = {c["id"]: c for c in json.loads((DATA / "courses.json").read_text(encoding="utf8"))}
programs = {p["id"]: p for p in json.loads((DATA / "programs.json").read_text(encoding="utf8"))}
prereqs = json.loads((DATA / "prereqs.json").read_text(encoding="utf8")) if (DATA / "prereqs.json").exists() else {}
for _p in programs.values():                                   # a course required elsewhere in the major can't also be an elective
    _fixed = {i for r in _p["requirements"] for ru in r["rules"] if not ru.get("set") for o in ru["options"] for i in o}
    for r in _p["requirements"]:
        for ru in r["rules"]:
            if ru.get("set"):
                ru["options"] = [o for o in ru["options"] if not set(o) & _fixed]
coreqs = set(json.loads((DATA / "coreqs.json").read_text())) if (DATA / "coreqs.json").exists() else set()
source = json.loads((DATA / "prereq_source.json").read_text()) if (DATA / "prereq_source.json").exists() else {}   # provenance
by_code = {c["code"]: c["id"] for c in courses.values()}

# Real class sections from CUNYfirst (backend/sections.py): {termId: {courseId: [section...]}}.
sections = json.loads((DATA / "sections.json").read_text(encoding="utf8")) if (DATA / "sections.json").exists() else {}
_meta = json.loads((DATA / "sections_meta.json").read_text(encoding="utf8")) if (DATA / "sections_meta.json").exists() else {}
SEASON = _meta.get("season", {})              # {"Fall": ["1269"], ...} -- term ids live in sections.py

# ---- Pathways (CUNY general education) -----------------------------------------------------------
AREA = {"English Composition": "EC", "Mathematical&QuantitativeReasoning": "MQR", "Life and Physical Sciences": "LPS",
        "World Cultures": "WCGI", "US Experience": "USED", "Creative Expression": "CE",
        "Individual and Society": "IS", "Scientific World": "SW"}
OPTION = {"Literature": "LIT", "Language": "LANG", "Science": "SCI", "Synthesis": "SYN", "Writing Intensive": "W"}
FLEX = {"WCGI", "USED", "CE", "IS", "SW"}
CO = {"LIT", "LANG", "SCI", "CO4"}   # College Option slots
gened = {}   # courseId -> {"area": "SW"|None, "opts": {"SCI", "W", ...}}
with open(ROOT / "data" / "gened.csv", encoding="utf8", errors="ignore") as f:
    for row in csv.DictReader(f):
        cid = by_code.get(row["Course"].strip())
        if not cid:
            continue
        g = gened.setdefault(cid, {"area": None, "opts": set()})
        g["area"] = next((v for k, v in AREA.items() if k in row["Pathways Area"]), g["area"])
        g["opts"] |= {v for k, v in OPTION.items() if k in row["Writing Intesive / College Options"]}
for cid, c in courses.items():                                   # any "W" course is Writing Intensive
    if c["code"].endswith("W"):
        gened.setdefault(cid, {"area": None, "opts": set()})["opts"].add("W")

# Structural rule from Pathways policy (independent of any course text): College Writing 2 requires College Writing 1.
_ec1 = [by_code[c] for c in ("ENGL 110", "ENGL 110H") if c in by_code]
for cid, g in gened.items():
    if g["area"] == "EC" and cid not in _ec1 and not any(set(grp) & set(_ec1) for grp in prereqs.get(cid, [])):
        prereqs.setdefault(cid, []).append(_ec1)

# (slot id, label, fit(courseId)) — in the order we fill them.  One course fills one slot; W overlaps.
def _area(a): return lambda cid: gened.get(cid, {}).get("area") == a
def _opt(o): return lambda cid: o in gened.get(cid, {}).get("opts", ())
SLOTS = [
    ("EC1", "College Writing 1 (ENGL 110)", lambda cid: courses[cid]["code"] in ("ENGL 110", "ENGL 110H")),
    ("EC2", "College Writing 2", _area("EC")),
    ("MQR", "Math & Quantitative Reasoning", _area("MQR")),
    ("LPS", "Life & Physical Sciences", _area("LPS")),
    ("WCGI", "World Cultures & Global Issues", _area("WCGI")),
    ("USED", "US Experience in its Diversity", _area("USED")),
    ("CE", "Creative Expression", _area("CE")),
    ("IS", "Individual & Society", _area("IS")),
    ("SW", "Scientific World", _area("SW")),
    ("FLEX", "Additional Flexible Core", lambda cid: gened.get(cid, {}).get("area") in FLEX),
    ("LIT", "College Option: Literature", _opt("LIT")),
    ("LANG", "College Option: Language", _opt("LANG")),
    ("SCI", "College Option: Science", _opt("SCI")),
    ("CO4", "College Option: Synthesis / additional", lambda cid: _opt("SYN")(cid) or gened.get(cid, {}).get("area") in FLEX | {"LPS"} or bool(gened.get(cid, {}).get("opts", set()) & {"LIT", "LANG", "SCI"})),
]


def pathways(taken):
    """Maximum bipartite matching of courses to slots (augmenting paths): one course fills one slot, so a course counted
    for Required/Flexible Core never also counts for College Option, and a major course listed under both (CSCI 111:
    SW + College Option Science) lands wherever it fills the most slots overall. W overlaps (below)."""
    fits = [[cid for cid in sorted(taken) if fit(cid)] for _, _, fit in SLOTS]
    match = {}                                                   # courseId -> slot index

    def augment(i, seen):
        for cid in fits[i]:
            if cid not in seen:
                seen.add(cid)
                if cid not in match or augment(match[cid], seen):
                    match[cid] = i
                    return True
        return False

    # scarce College Option slots (LIT/LANG/SCI) first so a double-listed major course lands there; catch-all CO4 last
    for i in sorted(range(len(SLOTS)), key=lambda i: (SLOTS[i][0] not in CO - {"CO4"}, SLOTS[i][0] == "CO4")):
        augment(i, set())
    by_slot = {i: cid for cid, i in match.items()}
    out = [{"slot": slot, "label": label, "course": by_slot.get(i)} for i, (slot, label, _) in enumerate(SLOTS)]
    w = [cid for cid in taken if _opt("W")(cid)][:2]
    out.append({"slot": "W", "label": "Writing Intensive (2)", "course": w[0] if w else None})
    out.append({"slot": "W2", "label": "Writing Intensive (2)", "course": w[1] if len(w) > 1 else None})
    return out


# ---- Major requirements ----------------------------------------------------------------------------
def major_progress(program, taken):
    out = []
    for req in program["requirements"]:
        have = need = 0
        missing = []   # options (OR-groups) still open
        for rule in req["rules"]:
            sat = [o for o in rule["options"] if any(i in taken for i in o)]
            need += rule["n"]
            have += sum(courses[next(i for i in o if i in taken)]["credits"] for o in sat) if rule["kind"] == "credits" else min(len(sat), rule["n"])
            if have < need:
                missing += [o for o in rule["options"] if o not in sat]
        out.append({"name": req["name"], "have": have, "need": need, "set": next((r["set"] for r in req["rules"] if r.get("set")), None),
                    "unit": "credits" if any(r["kind"] == "credits" for r in req["rules"]) else "courses", "missing": missing})
    return out


def level(cid):
    n = int(re.match(r"[0-9]+", courses[cid]["code"].split()[1]).group())
    return n // 10 if n >= 1000 else n                        # CUNY 4-digit codes: CHEM 1013 is 100-level


def verified(cid):
    """True when we have a prerequisite source for this course, or it is an intro (<200) course. 200+ courses with no
    known prerequisite are shown as 'unverified' so students confirm with an advisor."""
    return cid in source or cid in prereqs or level(cid) < 200


def validate(terms):
    """Re-check an approved plan term by term: every prerequisite group must be met by an EARLIER term
    (same term allowed only for coreq-able courses, precalc by placement). Returns violations."""
    out, before = [], set()
    for i, term in enumerate(terms):
        same = set(term)
        for cid in term:
            if cid not in courses:
                continue
            for group in prereqs.get(cid, []):
                ok = any(p in before for p in group) or placement(group) or (cid in coreqs and any(p in same for p in group))
                if not ok:
                    out.append({"id": cid, "term": i, "missing": group})
        before |= same
    return out


def placement(group):
    """ponytail: a prereq group made only of precalc-track MATH (below 120, or 122) is assumed met by placement exam."""
    def num(cid): return int(re.match(r"\d+", courses[cid]["code"].split()[1]).group())
    return all(courses[p]["subject"] == "MATH" and (num(p) < 120 or num(p) == 122) for p in group)


def prereqs_met(cid, taken):
    return all(any(p in taken for p in group) or placement(group) for group in prereqs.get(cid, []))


def offered_text(cid, term):
    """The catalog's `courseTypicallyOffered` prose. Nearly worthless on its own -- it is the literal string
    "Fall, Spring" for 3,611 of 3,834 courses -- so it is only the last resort in offered() below."""
    o = courses[cid]["offered"]
    return term in o or o in ("", "All Terms", "Offer as needed") if term in ("Summer", "Winter") else term in o or "All" in o or o in ("", "Offer as needed")


def sections_for(cid, term):
    """Real sections for this course in that season, newest scraped term first ([] if none)."""
    for t in SEASON.get(term, ()):
        if secs := sections.get(t, {}).get(cid):
            return secs
    return []


def offered(cid, term):
    """Does this course actually run that term?

    Real sections win, but ONLY to move a course between seasons. Absence from every scraped term falls back
    to the catalog prose, and that fallback is load-bearing -- do not "tighten" it. 2,730 of 3,834 catalog
    courses have no section in any scraped term, and they are not all dead: 14 of the 44 courses in the
    CSCI-BS requirements (CSCI 310, 335, 365, 383, ...) and PHYS 204/227 on the official degree map are among
    them, because electives rotate across years. Treating "no section" as "not offered" would delete a third
    of the major's elective list. What we CAN say confidently is the narrower claim below.
    """
    if not SEASON.get(term):
        return offered_text(cid, term)   # we scraped no term for this season (Winter): sections can say nothing
    if sections_for(cid, term):
        return True
    if any(cid in sections.get(t, {}) for t in sections):
        return False            # it runs at QC in another season -- for THAT we trust the section data
    return offered_text(cid, term)


def fits(sec, avail):
    """One section against the student's availability. Times are minutes past midnight, so an overlap is a
    single comparison. A section with no meeting time (asynchronous online, TBA) always fits."""
    for m in [sec] + (sec.get("extra") or []):
        if m.get("start") is None:
            continue
        if m["start"] < avail.get("earliest", 0) or m["end"] > avail.get("latest", 24 * 60):
            return False
        for day, s, e in avail.get("busy") or ():
            if day in m["days"] and m["start"] < e and s < m["end"]:
                return False
    return True


def available(cid, term, avail):
    """Sections of this course the student could actually attend. Returns None when we have no schedule
    data for it at all -- 'unknown', which must not be confused with 'nothing fits'."""
    secs = sections_for(cid, term)
    if not secs:
        return None
    return [s for s in secs if fits(s, avail)] if avail else secs


def map_rank(program, cid):
    """Position in the official degree map (earlier = smaller) or 99."""
    for i, sem in enumerate(program["semesters"]):
        if any(cid in slot["courses"] for slot in sem["slots"]):
            return i
    return 99


def candidates(program, taken, term, avail=None):
    taken = set(taken)
    major = major_progress(program, taken)
    slots = pathways(taken)
    open_slots = [(s["slot"], s["label"], fit) for s, (_, _, fit) in zip(slots, SLOTS) if not s["course"]]
    need_w = sum(1 for s in slots if s["slot"].startswith("W") and not s["course"])
    major_ids = {i for req in program["requirements"] for r in req["rules"] for o in r["options"] for i in o}
    major_subjects = {courses[i]["subject"] for i in major_ids if i in courses}
    eligible = {cid for cid in courses if cid not in taken and prereqs_met(cid, taken)}
    eligible |= {cid for cid in coreqs if cid not in taken and prereqs_met(cid, taken | eligible)}   # coreq: pair with a same-term course
    out = []
    for cid, c in courses.items():
        if cid not in eligible or not offered(cid, term) or c["credits"] == 0:
            continue
        secs = available(cid, term, avail)
        if secs == []:                       # has real sections, none the student can attend -- drop it
            continue                         # (None means "no schedule data", which is not a reason to drop)
        reason, score, key = None, None, cid
        for req in major:
            hit = next((o for o in req["missing"] if cid in o), None)
            if hit:
                label = req["name"].replace("Major Requirements - ", "Major ")
                if req.get("set"):                                # catalog course set, e.g. "Computer Science Electives"
                    reason, score, key = f"{label}: {req['set']} ({req['have']}/{req['need']} {req['unit']})", (2, c["code"]), cid
                elif len(hit) == 1 and req["unit"] == "courses":
                    reason, score, key = f"{label}: required", (0, map_rank(program, cid)), cid
                else:
                    reason, score, key = f"{label}: " + " or ".join(courses[i]["code"] for i in hit), (2, map_rank(program, cid)), "|".join(hit)
                break
        if not reason:
            slot = next((s for s in open_slots if s[2](cid)), None)
            if slot:
                reason, score, key = f"Pathways: {slot[1]}", (1, [s[0] for s in SLOTS].index(slot[0])), slot[0]
            elif need_w and _opt("W")(cid):
                reason, score, key = "Writing Intensive requirement", (3, level(cid)), "W"   # lowest-level W first: ENGL 165W, not ACCT 361W via ACCT 261
            elif cid in gened:
                reason, score = "Free elective (Pathways-listed)", (5, c["code"])
        if not reason:
            continue
        if (rank := map_rank(program, cid)) < 99:            # the official degree map's ordering wins
            score = (0, rank)
        out.append({"id": cid, "reason": reason, "score": score, "key": key,
                    "verified": verified(cid), "source": source.get(cid, "policy" if cid in prereqs else None),
                    "sections": secs[:6] if secs else None})   # null = no schedule data, shown as such
    # tie-break: prefer courses that are prerequisites of something on the official degree map (e.g. PHYS 103 over ASTR 2)
    map_prereqs = {p for sem in program["semesters"] for slot in sem["slots"] for cid in slot["courses"] for g in prereqs.get(cid, []) for p in g}
    out.sort(key=lambda x: (x["score"], x["id"] not in map_prereqs, courses[x["id"]]["code"]))
    buckets, kept = {}, []                                    # keep variety: <=8 per Pathways slot, <=25 per other kind
    for x in out:
        b = ("P", x["key"]) if x["score"][0] == 1 else x["score"][0]
        if buckets.get(b, 0) < (8 if x["score"][0] == 1 else 25):
            kept.append(x); buckets[b] = buckets.get(b, 0) + 1
    out = kept
    for x in out[:80]:
        x["unlocks"] = sorted((o for o in courses if o not in taken and not prereqs_met(o, taken) and prereqs_met(o, taken | {x["id"]})),
                              key=lambda o: (o not in major_ids, courses[o]["code"]))
    return out[:80], {"major": major, "pathways": slots, "credits": sum(courses[i]["credits"] for i in taken if i in courses)}


def pick(cands, taken, locked=(), order=()):
    """Fill a term. `locked` (pins/queue) go in unconditionally, then `order` (Gemini's picks) and finally the rule-based
    phases (required core <=3 -> one catalog elective -> Pathways/W -> more electives -> free electives), every one
    through the same guards: <=MAX_CREDITS, <=5 per subject, coreq partner present, one course per Pathways slot.
    Stops once the term has >=MIN_COURSES and ~TARGET_CREDITS."""
    picked, credits, per_subject, used = [], 0, {}, {}
    ids = lambda: taken | {p["id"] for p in picked}
    full = lambda: credits >= TARGET_CREDITS and len(picked) >= MIN_COURSES

    def add(c, force=False):
        nonlocal credits
        if any(p["id"] == c["id"] for p in picked):
            return False
        subj, cr = courses[c["id"]]["subject"], courses[c["id"]]["credits"]
        if not force:
            if used.get(c["key"], 0) >= (2 if c["key"] == "W" else 1) or per_subject.get(subj, 0) >= 5 or credits + cr > MAX_CREDITS:
                return False
            if not prereqs_met(c["id"], ids()):                   # a coreq course needs its partner picked too
                return False
            if c["reason"].startswith("Pathways") and any(x["slot"] == c["key"] and x["course"] for x in pathways(ids())):
                return False                                      # a course already picked this term fills that slot
        picked.append(c); credits += cr; per_subject[subj] = per_subject.get(subj, 0) + 1; used[c["key"]] = used.get(c["key"], 0) + 1
        return True

    for c in locked:
        add(c, force=True)
    for c in order:
        if not full():
            add(c)
    core = [c for c in cands if c["score"][0] == 0]
    electives = sorted((c for c in cands if c["score"][0] == 2 and "Major " in c["reason"] and c["key"] == c["id"]),
                       key=lambda c: (-courses[c["id"]]["credits"], courses[c["id"]]["code"]))
    free = [c for c in cands if c["reason"].startswith("Free")]
    rest = [c for c in cands if c not in core and c not in electives and c not in free]
    for c in core[:8]:
        if full() or sum(1 for p in picked if p["score"][0] == 0) >= 3:
            break
        add(c)
    if not full() and not any(p in electives for p in picked):
        for c in electives:
            if add(c):
                break
    for c in rest + electives + free:
        if full() or len(picked) >= 7:
            break
        add(c)
    return picked


def when(c):
    """'TuTh 1:40PM-2:30PM' for the first fitting section, or '' when we have no schedule for it."""
    s = (c.get("sections") or [None])[0]
    if not s or s.get("start") is None:
        return ""
    fmt = lambda m: f"{(m // 60 - 1) % 12 + 1}:{m % 60:02d}{'AM' if m < 720 else 'PM'}"
    return f'{s["days"]} {fmt(s["start"])}-{fmt(s["end"])}'


def gemini_order(program, term, cands, locked, progress, avail=None):
    """Gemini's ordered picks (candidate dicts with its one-line reason), or None (no key / failure)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    major_ids = {i for req in program["requirements"] for r in req["rules"] for o in r["options"] for i in o}
    lines = [f'{c["id"]} | {courses[c["id"]]["code"]} {courses[c["id"]]["name"]} | {courses[c["id"]]["credits"]} cr | {c["reason"]} | {when(c)} | unlocks: '
             + ", ".join(courses[u]["code"] for u in c["unlocks"] if u in major_ids)   # only major unlocks: a gen-ed chain (ACCT 261 -> 361W) is never a reason
             for c in cands[:40] if c not in locked]
    lcr = sum(courses[c["id"]]["credits"] for c in locked)
    fixed = ("The student has already placed these in the term (keep them, do not repeat them): "
             + ", ".join(f'{courses[c["id"]]["code"]} ({courses[c["id"]]["credits"]} cr)' for c in locked) + f" = {lcr} credits.\n") if locked else ""
    # every listed course already fits the student's availability -- this only asks for a compact day/time spread
    sched = ("Every course listed below already fits the student's stated availability. Among equally good choices prefer\n"
             "a term whose meeting times cluster on fewer days and do not leave long midday gaps.\n") if avail else ""
    prompt = f"""You are an academic advisor at Queens College planning a {term} semester for a {program['name']} ({program['degree']}) student
who has completed {progress['credits']} credits. {fixed}Pick courses from the ELIGIBLE list only so the whole term has at least {MIN_COURSES} courses
and {TARGET_CREDITS}-{MAX_CREDITS} credits (so pick about {max(TARGET_CREDITS - lcr, 0)}-{MAX_CREDITS - lcr} more credits, {max(MIN_COURSES - len(locked), 0)} or more courses).
Balance major courses with Pathways (general education) courses, prefer courses that unlock the most major courses, and
avoid more than 2 courses of the same subject. Never take a course only to reach a later general-education or Writing
Intensive course: fill each Pathways or Writing Intensive slot with the lowest-level course that fits it directly. List them most important first.
{sched}Return ONLY JSON: {{"courses": [{{"id": "<id>", "reason": "<one short sentence for the student>"}}]}}

ELIGIBLE (id | course | credits | why it is needed | meeting time | what it unlocks):
""" + "\n".join(lines)
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}",
                                 data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            chosen = json.loads(json.load(r)["candidates"][0]["content"]["parts"][0]["text"])["courses"]
    except Exception as e:                                      # ponytail: any Gemini failure -> heuristic
        print("gemini failed:", e)
        return None
    valid = {c["id"]: c for c in cands}
    out = [dict(valid[x["id"]], reason=x.get("reason") or valid[x["id"]]["reason"]) for x in chosen if isinstance(x, dict) and x.get("id") in valid]
    return list({p["id"]: p for p in out}.values()) or None       # Gemini sometimes repeats a course


def unlocks(cid, base, program):
    """Courses whose prereqs are met with `base` (this plan) but NOT without `cid`: the course is *necessary* for them.
    Evaluated against the whole proposed term, so a course never 'unlocks' something its term-mate already covers."""
    with_c, without_c = base | {cid}, base - {cid}
    major_ids = {i for req in program["requirements"] for r in req["rules"] for o in r["options"] for i in o}
    return sorted((o for o in courses if o not in with_c and prereqs.get(o) and prereqs_met(o, with_c) and not prereqs_met(o, without_c)),
                  key=lambda o: (o not in major_ids, courses[o]["code"]))


_cache = {}   # ponytail: in-memory, per process; (program, terms, term, locked) -> response. Restart clears it.


def suggest(body):
    program = programs[body["program"]]
    term = body.get("term", "Fall")
    terms = body.get("terms") or ([body["taken"]] if body.get("taken") else [])   # ordered approved terms (or a flat list)
    taken = {i for t in terms for i in t}
    avail = body.get("avail") or None
    cands, progress = candidates(program, taken, term, avail)
    valid = {c["id"]: c for c in cands}
    locked = [valid[i] for i in dict.fromkeys(body.get("pins", []) + body.get("queue", [])) if i in valid]
    key = (body["program"], tuple(tuple(t) for t in terms), term, tuple(c["id"] for c in locked),
           json.dumps(avail, sort_keys=True))
    if not body.get("fresh") and key in _cache:
        return _cache[key]
    lcr = sum(courses[c["id"]]["credits"] for c in locked)
    order = None if lcr >= TARGET_CREDITS and len(locked) >= MIN_COURSES else gemini_order(program, term, cands, locked, progress, avail)
    picked = pick(cands, taken, locked, order or ())
    base = taken | {c["id"] for c in picked}
    for c in cands:                                    # recompute against the chosen term (candidates() used taken only)
        c["unlocks"] = unlocks(c["id"], base, program)
    strip = lambda c: {k: v for k, v in c.items() if k not in ("score", "key")}
    out = {"suggested": [strip(c) for c in picked], "candidates": [strip(c) for c in cands], "progress": progress,
           "source": "gemini" if order else "heuristic", "violations": validate(terms),
           # only the next term maps to a schedule the registrar has actually published; terms after it reuse
           # the same season's pattern, which is a fair guide but is not a booking. Say which, never imply both.
           "schedule": {"basis": "published" if not terms else "pattern", "scraped": _meta.get("scraped")} if sections else None}
    _cache[key] = out
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, status=200):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-headers", "content-type")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send({})

    def do_GET(self):
        if self.path == "/api/programs":
            return self._send([{"id": p["id"], "name": p["name"], "degree": p["degree"]} for p in programs.values()])
        if self.path == "/api/gened":                            # Pathways tags per course, for the add-course filter
            labels = {"EC": "English Composition", "MQR": "Math & Quantitative Reasoning", "LPS": "Life & Physical Sciences",
                      "WCGI": "World Cultures & Global Issues", "USED": "US Experience in its Diversity", "CE": "Creative Expression",
                      "IS": "Individual & Society", "SW": "Scientific World", "LIT": "College Option: Literature",
                      "LANG": "College Option: Language", "SCI": "College Option: Science", "SYN": "College Option: Synthesis", "W": "Writing Intensive"}
            return self._send({"labels": labels, "courses": {cid: ([g["area"]] if g["area"] else []) + sorted(g["opts"]) for cid, g in gened.items()}})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0)) or b"{}"))
        if self.path == "/api/suggest" and body.get("program") in programs:
            return self._send(suggest(body))
        self._send({"error": "bad request"}, 400)


if __name__ == "__main__":
    print(f"{len(courses)} courses, {len(programs)} programs, {len(prereqs)} with prereqs, {len(gened)} gen-ed; "
          f"gemini: {'on' if os.environ.get('GEMINI_API_KEY') else 'off (heuristic)'}")
    port = int(os.environ.get("PORT", 8000))   # ponytail: PORT= to run a second copy beside a live one
    print(f"listening on :{port}")
    ThreadingHTTPServer(("", port), Handler).serve_forever()
