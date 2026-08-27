"""Conflict-free class-section optimizer.

The academic planner decides *which courses* are worth taking. This module solves the
separate combinatorial problem: choose one real section for each requested course so
all meetings can coexist.

Hard constraints are always enforced:
  * one section per requested course
  * no overlapping meetings
  * optionally require sections whose CUNYfirst status is Open

Preferences are optional. With ``weights=None`` every feasible schedule is considered
equally good and results are returned in deterministic search order. This is the safe
MVP/default: we do not invent student preferences. A later Gemini/user-preference
layer can supply normalized weights in [0, 1] without changing the solver.

The search uses backtracking with the most-constrained-course-first (MRV) heuristic,
so it prunes a branch as soon as a newly chosen section conflicts with the partial
schedule instead of constructing the full Cartesian product first.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

DAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
DEFAULT_EARLY = 10 * 60       # 10:00 AM
DEFAULT_LATE = 17 * 60        # 5:00 PM
SUPPORTED_WEIGHTS = {"campus_days", "gap_minutes", "early_minutes", "late_minutes"}


@dataclass(frozen=True)
class Choice:
    """A chosen section paired with its course id."""

    course_id: str
    section: Mapping


def _day_set(raw: str) -> set[str]:
    """Convert the scraper's compact day string (e.g. ``MoWe`` or ``TuTh``) to a set."""
    raw = raw or ""
    return {d for d in DAYS if d in raw}


def meetings(section: Mapping) -> List[Mapping]:
    """Return the primary meeting plus any extra meetings (lab/recitation/etc.)."""
    return [section] + list(section.get("extra") or [])


def meetings_conflict(a: Mapping, b: Mapping) -> bool:
    """True when two individual meetings overlap on at least one common day.

    TBA/asynchronous meetings have no numeric time and are treated as non-conflicting;
    there is no honest time conflict to enforce until a time exists.
    """
    if a.get("start") is None or b.get("start") is None:
        return False
    if not (_day_set(a.get("days", "")) & _day_set(b.get("days", ""))):
        return False
    return a["start"] < b["end"] and b["start"] < a["end"]


def sections_conflict(a: Mapping, b: Mapping) -> bool:
    """True when any primary/extra meeting from section A conflicts with section B."""
    return any(meetings_conflict(ma, mb) for ma in meetings(a) for mb in meetings(b))


def compatible(section: Mapping, chosen: Sequence[Choice]) -> bool:
    """Whether ``section`` can be added to the partial schedule."""
    return all(not sections_conflict(section, item.section) for item in chosen)


def _is_open(section: Mapping) -> bool:
    """CUNYfirst uses Open / Closed / Wait List. Blank status is treated as unknown, not open."""
    return str(section.get("status", "")).strip().lower() == "open"


def _filtered_options(
    course_sections: Mapping[str, Sequence[Mapping]], open_only: bool
) -> Dict[str, List[Mapping]]:
    out: Dict[str, List[Mapping]] = {}
    for cid, options in course_sections.items():
        values = [s for s in options if (not open_only or _is_open(s))]
        # Deterministic order makes neutral-mode pagination stable across requests.
        values.sort(key=lambda s: (
            s.get("start") is None,
            s.get("start") if s.get("start") is not None else 24 * 60,
            s.get("days", ""),
            str(s.get("sec", "")),
        ))
        out[cid] = values
    return out


def feasible_schedules(
    course_sections: Mapping[str, Sequence[Mapping]], *, open_only: bool = True
) -> Iterator[List[Choice]]:
    """Yield conflict-free schedules lazily using backtracking + MRV.

    The function does *not* generate the Cartesian product up front. At each recursive
    step it chooses the remaining course with the fewest currently compatible sections,
    so impossible branches die as early as possible.
    """
    options = _filtered_options(course_sections, open_only)
    if not options or any(not values for values in options.values()):
        return

    remaining = tuple(sorted(options))

    def search(todo: Tuple[str, ...], chosen: List[Choice]) -> Iterator[List[Choice]]:
        if not todo:
            yield list(chosen)
            return

        compatible_by_course = {
            cid: [section for section in options[cid] if compatible(section, chosen)]
            for cid in todo
        }
        if any(not values for values in compatible_by_course.values()):
            return

        cid = min(todo, key=lambda c: (len(compatible_by_course[c]), c))
        rest = tuple(c for c in todo if c != cid)
        for section in compatible_by_course[cid]:
            chosen.append(Choice(cid, section))
            yield from search(rest, chosen)
            chosen.pop()

    yield from search(remaining, [])


def schedule_metrics(schedule: Sequence[Choice]) -> Dict[str, float]:
    """Compute preference attributes. Lower is better for every metric.

    Keeping every metric as a cost makes weights simple: a larger weight means
    "this matters more to me" without allowing Gemini to flip the sign.
    """
    per_day: Dict[str, List[Tuple[int, int]]] = {d: [] for d in DAYS}
    early = late = 0

    for choice in schedule:
        for meeting in meetings(choice.section):
            start, end = meeting.get("start"), meeting.get("end")
            if start is None or end is None:
                continue
            for day in _day_set(meeting.get("days", "")):
                per_day[day].append((start, end))
            early += max(0, DEFAULT_EARLY - start)
            late += max(0, end - DEFAULT_LATE)

    campus_days = sum(bool(v) for v in per_day.values())
    gaps = 0
    for values in per_day.values():
        values.sort()
        for (_, prev_end), (next_start, _) in zip(values, values[1:]):
            gaps += max(0, next_start - prev_end)

    return {
        "campus_days": float(campus_days),
        "gap_minutes": float(gaps),
        "early_minutes": float(early),
        "late_minutes": float(late),
    }


def normalize_weights(weights: Optional[Mapping[str, float]]) -> Optional[Dict[str, float]]:
    """Validate preference weights and normalize them to sum to 1.

    Input values must already be bounded to [0, 1]. ``None`` or all-zero weights means
    neutral mode: all feasible schedules rank equally and deterministic search order wins.
    """
    if not weights:
        return None
    unknown = set(weights) - SUPPORTED_WEIGHTS
    if unknown:
        raise ValueError(f"unknown optimizer weight(s): {', '.join(sorted(unknown))}")
    clean = {name: float(weights.get(name, 0.0)) for name in SUPPORTED_WEIGHTS}
    if any(value < 0 or value > 1 for value in clean.values()):
        raise ValueError("optimizer weights must be between 0 and 1")
    total = sum(clean.values())
    if total == 0:
        return None
    return {name: value / total for name, value in clean.items()}


def _cost(metrics: Mapping[str, float], weights: Mapping[str, float]) -> float:
    """Weighted human-scale cost used only for ordering feasible schedules."""
    return (
        weights["campus_days"] * metrics["campus_days"]
        + weights["gap_minutes"] * metrics["gap_minutes"] / 60.0
        + weights["early_minutes"] * metrics["early_minutes"] / 60.0
        + weights["late_minutes"] * metrics["late_minutes"] / 60.0
    )


def optimize(
    course_sections: Mapping[str, Sequence[Mapping]],
    *,
    limit: int = 10,
    offset: int = 0,
    weights: Optional[Mapping[str, float]] = None,
    open_only: bool = True,
    ranking_pool: int = 1000,
) -> Dict:
    """Return a page of feasible schedules.

    Neutral mode (no weights): lazily skip ``offset`` schedules and return the next
    ``limit``. It peeks one schedule beyond the page so ``next_offset`` is only emitted
    when a later page really exists; it still never materializes the full search space.

    Weighted mode: examine up to ``ranking_pool`` feasible schedules, rank that explored
    pool, then return the requested page. This is intentionally described as ranking an
    explored pool rather than claiming a global mathematical optimum.
    """
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if ranking_pool < limit + offset:
        ranking_pool = limit + offset

    normalized = normalize_weights(weights)
    stream = feasible_schedules(course_sections, open_only=open_only)

    if normalized is None:
        results = []
        seen = 0
        has_more = False
        for schedule in stream:
            if seen < offset:
                seen += 1
                continue
            if len(results) < limit:
                results.append(_serialize(schedule, None, None))
                seen += 1
                continue
            # One extra feasible schedule proves another page exists. Stop immediately.
            has_more = True
            break
        return {
            "schedules": results,
            "offset": offset,
            "next_offset": offset + len(results) if has_more else None,
            "weights": None,
            "ranking": "neutral",
        }

    explored = []
    for i, schedule in enumerate(stream):
        if i >= ranking_pool:
            break
        metrics = schedule_metrics(schedule)
        explored.append((_cost(metrics, normalized), schedule, metrics))
    explored.sort(key=lambda item: (item[0], _stable_key(item[1])))
    page = explored[offset:offset + limit]
    return {
        "schedules": [_serialize(schedule, cost, metrics) for cost, schedule, metrics in page],
        "offset": offset,
        "next_offset": offset + len(page) if offset + len(page) < len(explored) else None,
        "weights": normalized,
        "ranking": "weighted-explored-pool",
        "explored": len(explored),
    }


def _stable_key(schedule: Sequence[Choice]) -> Tuple:
    return tuple(sorted((c.course_id, str(c.section.get("sec", ""))) for c in schedule))


def _serialize(
    schedule: Sequence[Choice],
    cost: Optional[float],
    metrics: Optional[Mapping[str, float]],
) -> Dict:
    ordered = sorted(schedule, key=lambda c: c.course_id)
    out = {
        "sections": [{"course_id": c.course_id, "section": dict(c.section)} for c in ordered],
    }
    if cost is not None:
        out["cost"] = round(cost, 6)
        out["metrics"] = dict(metrics or {})
    return out
