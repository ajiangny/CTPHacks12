"""Regression checks for backend/sections.py: python backend/test_sections.py"""
from sections import parse, parse_status, status_counts


# Global Search currently renders misleading alt="Open" text even for waitlisted rows.
open_cell = '&nbsp;<img src="images/status_open.gif" alt="Open" title = "Open" align="right">'
wait_cell = '&nbsp;<img src="images/status_waiting.gif" alt="Open" title = "Wait" align="right">'
closed_cell = '&nbsp;<img src="images/status_closed.gif" alt="Open" title = "Closed" align="right">'

assert parse_status(open_cell) == "Open"
assert parse_status(wait_cell) == "Wait List"
assert parse_status(closed_cell) == "Closed"

# The title is preferred, but the icon filename is a safe fallback if the title is missing.
assert parse_status('<img src="images/status_waiting.gif" alt="Open">') == "Wait List"
assert parse_status('<img src="images/status_closed.gif" alt="Open">') == "Closed"
assert parse_status('<img alt="Open">') == ""  # alt alone is deliberately not trusted
print("status-cell parsing OK")


# End-to-end parser regression using the exact CSCI 111 / Akinlar status pattern that exposed the bug.
page = """
<span>&nbsp;<a id='imageDivLink1'>details</a>&nbsp;CSCI 111 - Intro Algorithmic Problem Solv</span>
<table><tr>
<td data-label="Section">221-LEC Regular</td>
<td data-label="DaysAndTimes">TuTh 1:40PM - 2:30PM</td>
<td data-label="Room">Remsen 100</td>
<td data-label="Instructor">Cuneyt Akinlar</td>
<td data-label="Instruction Mode">In Person</td>
<td data-label="Status">&nbsp;<img src="images/status_waiting.gif" alt="Open" title = "Wait" align="right"></td>
<td data-label="Course Topic"></td>
</tr></table>
"""
parsed = parse(page)
section = parsed["CSCI 111"][0]
assert section["sec"] == "221"
assert section["component"] == "LEC"
assert section["days"] == "TuTh"
assert section["start"] == 820 and section["end"] == 870
assert section["instr"] == "Cuneyt Akinlar"
assert section["status"] == "Wait List"
print("end-to-end wait-list regression OK")


# Metadata health counts should surface suspicious status distributions.
counts = status_counts({"course": [
    {"status": "Open"},
    {"status": "Closed"},
    {"status": "Wait List"},
    {"status": ""},
]})
assert counts == {"Open": 1, "Closed": 1, "Wait List": 1, "Unknown": 1}, counts
print("status metadata counts OK")

print("sections parser OK")
