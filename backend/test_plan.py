"""Self-check for the planner: python backend/test_plan.py"""
import os
from pathlib import Path
import server as s
os.environ.pop("GEMINI_API_KEY", None)          # deterministic: rule-based picker only (after import: server loads .env)

by_code = s.by_code
cs = lambda *codes: [by_code[c] for c in codes]

# prereq logic: CSCI 220 needs MATH 120 AND (MATH 151 or 141) AND CSCI 111; MATH 151's precalc prereq is placement
assert s.prereqs_met(by_code["MATH 151"], set())
assert not s.prereqs_met(by_code["CSCI 220"], set(cs("MATH 120", "CSCI 111")))
assert s.prereqs_met(by_code["CSCI 220"], set(cs("MATH 120", "MATH 141", "CSCI 111")))

# a fresh CS BS Fall semester contains ENGL 110 and CSCI 111 (coreq with MATH 151/120) and is ~15 credits
r = s.suggest({"program": "CSCI-BS", "taken": [], "term": "Fall"})
codes = {s.courses[x["id"]]["code"] for x in r["suggested"]}
assert {"ENGL 110", "CSCI 111"} <= codes, codes
assert len(r["suggested"]) >= s.MIN_COURSES and s.TARGET_CREDITS <= sum(s.courses[x["id"]]["credits"] for x in r["suggested"]) <= s.MAX_CREDITS
assert by_code["CSCI 211"] in next(x for x in r["suggested"] if s.courses[x["id"]]["code"] == "CSCI 111")["unlocks"]

progress = s.suggest({"program": "CSCI-BS", "terms": [cs("CSCI 111", "MATH 151")], "term": "Spring", "fresh": True})["progress"]
core = next(m for m in progress["major"] if m["name"] == "Major Requirements - Core")
math = next(m for m in progress["major"] if m["name"] == "Major Requirements - Math")
assert [by_code["CSCI 111"]] in core["completed"], core
assert [by_code["MATH 151"]] in math["completed"], math
audit = s.parse_degreeworks_text("""Degree Bachelor of Arts (BA)
Audit date 08/24/2026
Major Computer Science BA   Concentration None
Algorithmic Problem Solving I CSCI 111 Intro Algorithmic Problem Solv B+ 3 FALL 2023
Object Oriented Programming in C++ CSCI 211 Object-Oriented Program in C++ B+ 3 SPRING 2024
Database Systems CSCI 331 Database Systems IP (3) FALL 2026
Software Engineering CSCI 370 Software Engineering W 0 SPRING 2026
CSCI 320 Theory of Computation F 0 FALL 2025
""")
assert audit["program"] == "CSCI-BA", audit
assert [t["name"] for t in audit["terms"]] == ["Fall 2023", "Spring 2024", "Fall 2026"], audit["terms"]   # IP applies (DegreeWorks counts it); W/F do not
assert audit["terms"][0]["courses"] == cs("CSCI 111") and audit["terms"][1]["courses"] == cs("CSCI 211") and audit["terms"][2]["courses"] == cs("CSCI 331"), audit["terms"]
assert {c["code"] for c in audit["courses"]} == {"CSCI 111", "CSCI 211", "CSCI 331"}, audit["courses"]
# approved non-CS electives: one counts toward CSCI electives, a second does not
el = lambda taken: next(m for m in s.major_progress(s.programs["CSCI-BS"], set(taken)) if "Electives" in m["name"])
assert el(cs("MATH 245"))["have"] == 3, el(cs("MATH 245"))
assert len(el(cs("MATH 245", "MATH 202"))["completed"]) == 1, el(cs("MATH 245", "MATH 202"))   # only one of them counts
assert not any(by_code["MATH 202"] in o for o in el(cs("MATH 245"))["missing"]), "second non-CS elective should not be offered"
print("non-CS electives OK")

calc_audit = [{"title": "CALCULUS REQUIREMENT", "parent": "MATH REQUIREMENT", "courses": cs("MATH 141", "MATH 142", "MATH 143"), "page": 1}]
calc_terms = [cs("MATH 120", "MATH 141", "MATH 142", "MATH 143", "MATH 231", "MATH 241")]
calc_prog = s.suggest({"program": "CSCI-BS", "terms": calc_terms, "term": "Fall", "fresh": True, "auditRequirements": calc_audit})["progress"]
calc_math = next(m for m in calc_prog["major"] if m["name"] == "Major Requirements - Math")
assert calc_math["have"] >= calc_math["need"] and not calc_math["missing"], calc_math
calc_cands = s.suggest({"program": "CSCI-BS", "terms": calc_terms, "term": "Fall", "fresh": True, "auditRequirements": calc_audit})["candidates"]
assert not {"MATH 151", "MATH 152"} & {s.courses[x["id"]]["code"] for x in calc_cands}, calc_cands

sample = Path(r"C:\Users\kevin\Downloads\audit-24272623-AM459aY1.pdf")
if sample.exists():
    parsed_pdf = s.parse_audit_pdf(sample.read_bytes())
    by_title = {r["title"]: [s.courses[i]["code"] for i in r["courses"]] for r in parsed_pdf["completedRequirements"]}
    assert by_title["CALCULUS REQUIREMENT"] == ["MATH 141", "MATH 142", "MATH 143"], by_title.get("CALCULUS REQUIREMENT")
    assert by_title["MATH REQUIREMENT"] == ["MATH 120", "MATH 231", "MATH 141", "MATH 142", "MATH 143", "MATH 241"], by_title.get("MATH REQUIREMENT")
    assert "Computer Architecture" not in by_title and "Software Engineering" not in by_title, by_title

# Pathways: one course fills one slot; ENGL 110 only fits EC1; CSCI 111 (SW + College Option Science) goes to College Option
p = {x["slot"]: x["course"] for x in s.pathways(set(cs("ENGL 110", "CSCI 111")))}
assert p["EC1"] == by_code["ENGL 110"] and p["SCI"] == by_code["CSCI 111"] and p["SW"] is None and p["EC2"] is None, p

# eight approved terms complete the major and every Pathways slot
taken = []
for term in ("Fall", "Spring") * 4:
    taken += [x["id"] for x in s.suggest({"program": "CSCI-BS", "taken": taken, "term": term})["suggested"]]
prog = s.suggest({"program": "CSCI-BS", "taken": taken, "term": "Fall"})["progress"]
assert prog["credits"] >= 120 and all(m["have"] >= m["need"] for m in prog["major"]) and all(x["course"] for x in prog["pathways"]), prog
print("planner OK")

# structural + description-derived prereqs: any College Writing 2 course needs ENGL 110 first
f1 = {s.courses[x["id"]]["code"] for x in s.suggest({"program": "CSCI-BS", "taken": [], "term": "Fall"})["candidates"]}
assert "ENGL 110" in f1 and "ENGL 130" not in f1 and "LIBR 170" not in f1, sorted(c for c in f1 if c.startswith("ENGL"))
assert s.prereqs_met(by_code["ENGL 130"], {by_code["ENGL 110"]})
print("prereq layers OK")

# plan validation: CSCI 313 before CSCI 220 is a violation; PHYS 103 with MATH 152 in the same term is fine (coreq)
v = s.validate([cs("CSCI 111", "MATH 151"), cs("CSCI 313")])
assert v and v[0]["id"] == by_code["CSCI 313"], v
assert not s.validate([cs("MATH 151"), cs("PHYS 103", "MATH 152")])
assert s.validate([cs("PHYS 103")])                       # coreq alone, with no calculus anywhere, is still a violation
assert not s.verified(by_code["CSCI 3981"]) and s.verified(by_code["CSCI 313"]) and s.verified(by_code["ENGL 110"])
print("validation OK")

# pins/queue: an eligible pinned course is locked into the term first; the rest is filled around it under the same caps
r = s.suggest({"program": "CSCI-BS", "terms": [], "term": "Fall", "pins": cs("MATH 141"), "queue": cs("CSCI 313")})
ids = [x["id"] for x in r["suggested"]]
assert ids[0] == by_code["MATH 141"] and by_code["CSCI 313"] not in ids, ids       # CSCI 313 not eligible yet -> ignored
assert len(ids) >= s.MIN_COURSES and sum(s.courses[i]["credits"] for i in ids) <= s.MAX_CREDITS
assert not s.validate([ids])                                                       # the term the picker builds is prereq-valid

# Gemini's order goes through the guards: a 20+ credit or duplicate-subject order gets trimmed, then topped up
cands, _ = s.candidates(s.programs["CSCI-BS"], set(), "Fall")
big = [c for c in cands if s.courses[c["id"]]["subject"] == "CSCI"] + cands
p = s.pick(cands, set(), (), big)
assert len(p) >= s.MIN_COURSES and sum(s.courses[c["id"]]["credits"] for c in p) <= s.MAX_CREDITS and len({c["id"] for c in p}) == len(p)

# cache: same input -> same object; fresh -> recomputed
a = s.suggest({"program": "CSCI-BS", "terms": [], "term": "Fall"}); b = s.suggest({"program": "CSCI-BS", "terms": [], "term": "Fall"})
assert a is b and s.suggest({"program": "CSCI-BS", "terms": [], "term": "Fall", "fresh": True}) is not a
print("locks + guards + cache OK")

# Pathways matching: a course listed under Core AND College Option (CSCI 111: SW + Science) moves to College Option when
# another course can take SW, so both slots fill; a Core-used course never also fills College Option (one course, one slot)
p = {x["slot"]: x["course"] for x in s.pathways(set(cs("CSCI 111", "ASTR 1")))}
assert p["SW"] and p["SCI"] == by_code["CSCI 111"], p
assert sum(1 for x in s.pathways(set(cs("CSCI 111"))) if x["course"]) == 1

# Writing Intensive: lowest-level W course first, never a prerequisite chain (ACCT 261 -> 361W) just to reach one
r = s.suggest({"program": "CSCI-BS", "terms": [cs("ENGL 110", "MATH 151", "CSCI 111")], "term": "Spring"})
w = [x for x in r["candidates"] if x["reason"] == "Writing Intensive requirement"]
assert all(s.level(a["id"]) <= s.level(b["id"]) for a, b in zip(w, w[1:])), [s.courses[x["id"]]["code"] for x in w[:5]]
print("pathways matching + W OK")

# elective subject preferences are soft tie-breakers for flexible requirements only
preferred, _ = s.candidates(s.programs["CSCI-BS"], set(), "Fall", preferences={"preferredSubjects": ["PSYCH"]})
mqr = [x for x in preferred if x["reason"].startswith("Pathways: Math & Quantitative Reasoning")]
assert s.courses[mqr[0]["id"]]["subject"] == "PSYCH", [s.courses[x["id"]]["code"] for x in mqr[:5]]
assert "matches your PSYCH preference" in mqr[0]["reason"]

avoided, _ = s.candidates(s.programs["CSCI-BS"], set(), "Fall", preferences={"avoidedSubjects": ["ASTR"]})
lps = [x for x in avoided if x["reason"].startswith("Pathways: Life & Physical Sciences")]
subjects = [s.courses[x["id"]]["subject"] for x in lps]
assert "ASTR" in subjects and subjects.index("ASTR") > next(i for i, subject in enumerate(subjects) if subject != "ASTR"), subjects

plain, _ = s.candidates(s.programs["CSCI-BS"], set(), "Fall")
major_plain = [(x["id"], x["score"]) for x in plain if x["reason"].startswith("Major")]
major_preferred = [(x["id"], x["score"]) for x in preferred if x["reason"].startswith("Major")]
assert major_preferred == major_plain

# preferences participate in cache identity while omission remains backward compatible
base = s.suggest({"program": "CSCI-BS", "terms": [], "term": "Fall"})
with_preferences = s.suggest({"program": "CSCI-BS", "terms": [], "term": "Fall", "preferences": {"preferredSubjects": ["PSYCH"]}})
assert with_preferences is not base
print("elective preferences OK")

# ---- schedules & availability (backend/sections.py) ---------------------------------------------------
if s.sections:
    # offered() is now driven by real sections, not the catalog's "Fall, Spring" prose
    everywhere = {cid for t in s.sections for cid in s.sections[t]}
    fall = set(s.sections.get(s.SEASON["Fall"][0], {}))
    assert fall, "no Fall sections scraped"
    assert s.offered(by_code["CSCI 111"], "Fall")
    off_season = next((c for c in everywhere - fall), None)       # runs at QC, but not in the Fall
    assert off_season is None or not s.offered(off_season, "Fall"), s.courses[off_season]["code"]
    # a course absent from EVERY scraped term keeps the old prose fallback rather than vanishing
    ghost = next((c for c in s.courses if c not in everywhere), None)
    assert ghost is None or s.offered(ghost, "Fall") == s.offered_text(ghost, "Fall")
    # ...and that fallback is load-bearing: CS electives rotate across years, so "no section scraped" must
    # never mean "not offered". If this fires, offered() was tightened and the major lost elective options.
    rotating = [c for c in cs("CSCI 310", "CSCI 335", "CSCI 365", "CSCI 383") if c not in everywhere]
    assert all(s.offered(c, "Fall") for c in rotating), [s.courses[c]["code"] for c in rotating]

    # a section that clashes with a busy block does not fit; one with no meeting time always does
    secs = [x for x in s.sections_for(by_code["CSCI 111"], "Fall") if x["start"] is not None]
    assert secs, "CSCI 111 has no timed Fall section"
    one = secs[0]
    busy = {"busy": [[one["days"][:2], one["start"], one["end"]]], "earliest": 0, "latest": 24 * 60}
    assert not s.fits(one, busy)
    assert s.fits(one, {"busy": [[one["days"][:2], one["end"], one["end"] + 30]], "earliest": 0, "latest": 24 * 60})
    assert s.fits({"start": None, "end": None, "days": "", "extra": []}, busy)

    # a course whose every section falls inside the busy window is dropped from the candidate list
    all_secs = s.sections_for(by_code["CSCI 111"], "Fall")
    block = {"busy": [[d, 0, 24 * 60] for d in ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")], "earliest": 0, "latest": 24 * 60}
    if all(x["start"] is not None for x in all_secs):
        assert s.available(by_code["CSCI 111"], "Fall", block) == []
        blocked_ids = {c["id"] for c in s.candidates(s.programs["CSCI-BS"], set(), "Fall", block)[0]}
        assert by_code["CSCI 111"] not in blocked_ids

    # the filter is INERT when the student has narrowed nothing: same term as with no availability at all
    wide = {"busy": [], "earliest": 0, "latest": 24 * 60}
    base = [x["id"] for x in s.suggest({"program": "CSCI-BS", "terms": [], "term": "Fall"})["suggested"]]
    same = [x["id"] for x in s.suggest({"program": "CSCI-BS", "terms": [], "term": "Fall", "avail": wide})["suggested"]]
    assert base == same, (base, same)

    # a real narrowing changes nothing structural: still a legal, prereq-valid term
    late = {"busy": [], "earliest": 11 * 60, "latest": 22 * 60}
    r = s.suggest({"program": "CSCI-BS", "terms": [], "term": "Fall", "avail": late})
    for x in r["suggested"]:
        for sec in (x["sections"] or []):
            assert sec["start"] is None or sec["start"] >= 11 * 60, (s.courses[x["id"]]["code"], sec)
    assert not s.validate([[x["id"] for x in r["suggested"]]])
    print("schedules + availability OK")
else:
    print("schedules SKIPPED (run: python backend/sections.py)")

# advisor chat: builds the student context and degrades cleanly without a key (never calls Gemini here)
os.environ.pop("GEMINI_API_KEY", None)
ctx = s.chat_context(s.programs["CSCI-BS"], [[s.by_code["CSCI 111"], s.by_code["ENGL 110"]]], "Spring")
assert "CSCI 111" in ctx and "APPROVED PLAN" in ctx and "ELIGIBLE NEXT SPRING" in ctx, ctx[:300]
assert "CSCI 211" in ctx or "CSCI 212" in ctx, "CSCI 111 should unlock 211/212 in the eligible list"
r = s.chat({"program": "CSCI-BS", "terms": [], "term": "Fall", "messages": [{"role": "user", "text": "hi"}]})
assert r["source"] == "none" and "GEMINI_API_KEY" in r["reply"], r
assert "error" in s.chat({"program": "CSCI-BS", "terms": [], "messages": [{"role": "model", "text": "x"}]})
print("advisor chat OK")

# fastest track: from nothing -> a multi-term path that finishes the CS major; from approved terms -> continues, no repeats
track = s.fast_track(s.programs["CSCI-BS"], [], "Fall")
assert 4 <= len(track) <= s.MAX_TRACK_TERMS and track[0]["term"] == "Fall" and track[1]["term"] == "Spring", [t["term"] for t in track]
assert s.by_code["CSCI 111"] in track[0]["courses"], "CSCI 111 first"
flat = [i for t in track for i in t["courses"]]
assert len(flat) == len(set(flat)), "no course twice"
assert not s.validate([t["courses"] for t in track]), "every term prereq-valid"
assert all(m["have"] >= m["need"] for m in s.candidates(s.programs["CSCI-BS"], s.Counter(flat), "Fall")[1]["major"]), "major complete"
first = [s.by_code["CSCI 111"], s.by_code["ENGL 110"], s.by_code["MATH 151"]]
cont = s.fast_track(s.programs["CSCI-BS"], [first], "Spring")
assert cont[0]["term"] == "Spring" and not set(first) & {i for t in cont for i in t["courses"]}, "continues after approved term"
assert s.FAST_TRACK_RE.search("what's the fastest track to graduate?") and not s.FAST_TRACK_RE.search("what is CSCI 111?")
print("fastest track OK")
