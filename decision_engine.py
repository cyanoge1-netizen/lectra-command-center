"""Phase C — decision layer.

Pure, deterministic helpers that rank "what to do next" from the broker
state graph, so the UI (Today Brief, Home Cockpit) can surface one ranked
list instead of raw numbers. No Qt imports here; every function is testable
with plain dicts.

Data it reads (all already present in the broker):
  * syllabus.semesters : {sem: {code: {topics: [{name, yield, status}]}}}
  * syllabus.exams     : [ {course, title, date, instructor} ]
  * homework           : [ {course, title, due_date, done, instructor} ]
  * assignments        : [ {course, title, due_date, done, instructor} ]
  * attendance.records : {code: {"YYYY-MM-DD": "present"|"absent"|...}}
  * attendance.risk_threshold : int %
  * checklist.log      : { "YYYY-MM-DD": ["CODE|topic", ...] }  (last review)
"""

import math
from datetime import date

YIELD_REVIEW_DAYS = {"high": 3, "medium": 5, "low": 7}
DEFAULT_REVIEW_DAYS = 7

KIND_ICON = {
    "homework": "\U0001F4DA",
    "assignment": "\U0001F4C4",
    "study": "\U0001F4D8",
    "attendance": "\U0001F3AF",
    "revision": "\U0001F504",
}


def _iter_courses(broker):
    """Yield (semester, code, course) rows for the active semester (falling
    back to every semester when none is active), mirroring syllabus_tab."""
    sems = broker.get("syllabus.semesters", {}) or {}
    active = broker.get("syllabus.active_semester")
    keys = [active] if (active and active in sems) else list(sems.keys())
    for sem in keys:
        for code, course in (sems.get(sem) or {}).items():
            yield sem, code, course


def attendance_counts(records, code):
    """(present, absent) marks for a course. Cancelled classes never count."""
    rec = ((records or {}).get(code, {}) or {})
    present = absent = 0
    for status in rec.values():
        s = str(status).strip().lower()
        if s == "present":
            present += 1
        elif s == "absent":
            absent += 1
    return present, absent


def attendance_rate(records, code):
    """Return present/(present+absent) for a course, or None when unmarked.
    Cancelled classes never count toward the rate."""
    present, absent = attendance_counts(records, code)
    if present + absent == 0:
        return None
    return present / (present + absent)


def classes_to_recover(present, total, threshold):
    """Consecutive present classes needed to lift ``present``/``total`` to
    ``threshold`` percent. Returns 0 when already at/above threshold."""
    if threshold <= 0 or total <= 0:
        return 0
    t = threshold / 100.0
    if present / total >= t:
        return 0
    need = (t * total - present) / (1 - t)
    return max(0, int(math.ceil(need)))


def course_exam(exams, code, today=None):
    """Nearest upcoming exam date for a course code, else None."""
    today = today or date.today()
    best = None
    for ex in exams or []:
        if str(ex.get("course", "")).strip().upper() != code.upper():
            continue
        try:
            d = date.fromisoformat(ex["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if d < today:
            continue
        if best is None or d < best:
            best = d
    return best


def last_reviewed(log, code, topic):
    """Latest date a topic was checked off in the checklist log, else None."""
    best = None
    needle = f"{code}|{topic}"
    for day, entries in (log or {}).items():
        if needle in (entries or []):
            try:
                d = date.fromisoformat(str(day))
            except ValueError:
                continue
            if best is None or d > best:
                best = d
    return best


def topic_status(topic):
    return str((topic or {}).get("status", "")).strip().lower()


def topic_yield(topic):
    return str((topic or {}).get("yield", "")).strip().lower()


def _deadline_actions(broker, today):
    """Pending homework/assignments scored by days-to-due. Assignments weigh
    slightly more than homework at equal distance."""
    actions = []
    for kind, mult in (("homework", 1.0), ("assignment", 1.4)):
        section = "homework" if kind == "homework" else "assignments"
        for item in broker.get(section, []) or []:
            if item.get("done"):
                continue
            due = item.get("due_date")
            if not due:
                continue
            try:
                d = date.fromisoformat(due)
            except (TypeError, ValueError):
                continue
            delta = (d - today).days
            if delta < 0:
                score = 100 + min(20, -delta * 2)
                reason = f"OVERDUE by {-delta}d — {due}"
            elif delta == 0:
                score = 90
                reason = "due today"
            elif delta <= 2:
                score = 82 - delta * 4
                reason = f"due in {delta}d"
            elif delta <= 7:
                score = 66 - delta * 3
                reason = f"due in {delta}d"
            else:
                score = 30 - delta
            score = int(round(score * mult))
            if score <= 0:
                continue
            actions.append({
                "kind": kind,
                "score": score,
                "title": item.get("title") or "Untitled",
                "course": item.get("course") or "",
                "reason": reason,
                "days": delta,
                "date": due,
                "tab": 0,
            })
    return actions


def _study_actions(broker, today):
    """One action per course with unstudied topics, combining exam proximity,
    high-yield backlog and attendance risk."""
    threshold = broker.get("attendance.risk_threshold", 75)
    exams = broker.get("syllabus.exams", []) or []
    records = broker.get("attendance.records", {}) or {}
    actions = []
    for _sem, code, course in _iter_courses(broker):
        topics = course.get("topics", []) or []
        pending = [t for t in topics
                   if isinstance(t, dict) and topic_status(t) != "completed"]
        if not pending:
            continue
        high = [t for t in pending if topic_yield(t) == "high"]
        ex = course_exam(exams, code, today)
        days = (ex - today).days if ex else None
        rate = attendance_rate(records, code)
        score = 0
        reasons = []
        if days is not None and days <= 14:
            score += max(0, 90 - days * 2)
            reasons.append(f"exam in {days}d")
        elif days is not None:
            score += 20
            reasons.append(f"exam in {days}d")
        if high:
            score += min(24, len(high) * 6)
            reasons.append(f"{len(high)} high-yield topic{'s' if len(high) > 1 else ''} left")
        if rate is not None and rate * 100 < threshold:
            score += 15
            reasons.append(f"attendance {rate * 100:.0f}%")
        if score == 0:
            score = 8
            reasons.append("unstudied topics pending")
        actions.append({
            "kind": "study",
            "score": min(99, score),
            "title": f"Study {code}",
            "course": code,
            "reason": " · ".join(reasons),
            "days": days,
            "date": ex.isoformat() if ex else None,
            "tab": 8,
        })
    return actions


def _attendance_actions(broker, today):
    """Courses below the attendance risk threshold, with a concrete recovery
    target (classes to attend in a row)."""
    threshold = broker.get("attendance.risk_threshold", 75)
    records = broker.get("attendance.records", {}) or {}
    actions = []
    for code in (records or {}):
        present, absent = attendance_counts(records, code)
        total = present + absent
        if total == 0:
            continue
        rate = present / total
        need = classes_to_recover(present, total, threshold)
        if need <= 0:
            continue
        actions.append({
            "kind": "attendance",
            "score": 78 - min(12, need * 2),
            "title": f"Fix attendance in {code}",
            "course": code,
            "reason": f"{rate * 100:.0f}% < {threshold}% — attend {need} in a row to recover",
            "days": None,
            "date": None,
            "tab": 3,
        })
    return actions


def _revision_actions(broker, today):
    """Completed topics whose checklist review is older than their yield
    interval — the spaced-repetition queue."""
    log = broker.get("checklist.log", {}) or {}
    actions = []
    for _sem, code, course in _iter_courses(broker):
        for topic in course.get("topics", []) or []:
            if not isinstance(topic, dict) or topic_status(topic) != "completed":
                continue
            name = topic.get("name") or ""
            if not name:
                continue
            reviewed = last_reviewed(log, code, name)
            if reviewed is None:
                continue
            days_since = (today - reviewed).days
            interval = YIELD_REVIEW_DAYS.get(topic_yield(topic), DEFAULT_REVIEW_DAYS)
            if days_since < interval:
                continue
            actions.append({
                "kind": "revision",
                "score": min(46, 18 + days_since * 2),
                "title": f"Revise {name}",
                "course": code,
                "reason": f"last reviewed {days_since}d ago ({reviewed.isoformat()})",
                "days": days_since,
                "date": reviewed.isoformat(),
                "tab": 8,
            })
    return actions


def next_actions(broker, today=None, limit=15):
    """Ranked list of suggested next actions across every source, best first.
    Each item: {kind, score, title, course, reason, days, date, tab}."""
    today = today or date.today()
    actions = (
        _deadline_actions(broker, today)
        + _study_actions(broker, today)
        + _attendance_actions(broker, today)
        + _revision_actions(broker, today)
    )
    actions.sort(key=lambda a: a["score"], reverse=True)
    return actions[:limit]


def revision_due(broker, today=None):
    """Completed topics currently past their review interval. Items mirror
    the action dict (kind 'revision') with an extra ``yield`` field."""
    today = today or date.today()
    log = broker.get("checklist.log", {}) or {}
    out = []
    for _sem, code, course in _iter_courses(broker):
        for topic in course.get("topics", []) or []:
            if not isinstance(topic, dict) or topic_status(topic) != "completed":
                continue
            name = topic.get("name") or ""
            if not name:
                continue
            reviewed = last_reviewed(log, code, name)
            if reviewed is None:
                continue
            y = topic_yield(topic)
            interval = YIELD_REVIEW_DAYS.get(y, DEFAULT_REVIEW_DAYS)
            days_since = (today - reviewed).days
            if days_since < interval:
                continue
            out.append({
                "kind": "revision",
                "score": min(46, 18 + days_since * 2),
                "title": name,
                "course": code,
                "yield": y,
                "reason": f"last reviewed {days_since}d ago",
                "days": days_since,
                "date": reviewed.isoformat(),
                "tab": 8,
            })
    out.sort(key=lambda a: a["score"], reverse=True)
    return out
