# Tests for decision_engine.py (stdlib unittest — no pytest needed).
#
# Run:  python3 -m unittest discover -s tests -v
import unittest
from datetime import date, timedelta

from decision_engine import (attendance_rate, classes_to_recover,
                             course_exam, last_reviewed, next_actions,
                             revision_due)


def _broker(**overrides):
    base = {
        "syllabus.semesters": {
            "semester_1": {
                "CSE101": {
                    "topics": [
                        {"name": "Arrays", "yield": "high", "status": "Completed"},
                        {"name": "Linked Lists", "yield": "high", "status": "Studying"},
                    ],
                },
                "MATH201": {
                    "topics": [
                        {"name": "Eigenvalues", "yield": "high", "status": "Pending"},
                    ],
                },
            },
        },
        "syllabus.active_semester": "semester_1",
        "syllabus.exams": [
            {"course": "MATH201", "title": "Term Exam", "date": "2026-12-01"},
        ],
        "homework": [
            {"course": "CSE101", "title": "HW1", "due_date": "2026-08-01", "done": False},
        ],
        "assignments": [],
        "attendance.records": {
            "CSE101": {"2026-07-01": "present", "2026-07-02": "absent",
                       "2026-07-03": "cancelled"},
        },
        "attendance.risk_threshold": 75,
        "checklist.log": {
            "2026-08-01": ["CSE101|Arrays"],
        },
        "checklist.custom_tasks": [],
    }
    base.update(overrides)
    return _FakeBroker(base)


class _FakeBroker:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


class AttendanceTest(unittest.TestCase):

    def test_rate_ignores_cancelled(self):
        self.assertAlmostEqual(attendance_rate(
            {"CSE101": {"a": "present", "b": "absent", "c": "cancelled"}},
            "CSE101"), 0.5)

    def test_rate_none_when_unmarked(self):
        self.assertIsNone(attendance_rate({}, "CSE101"))

    def test_classes_to_recover(self):
        # 3/4 = 75% already at threshold -> 0
        self.assertEqual(classes_to_recover(3, 4, 75), 0)
        # 2/4 = 50% needs 4 in a row to hit 75% (6/8)
        self.assertEqual(classes_to_recover(2, 4, 75), 4)
        # degenerate inputs -> 0
        self.assertEqual(classes_to_recover(0, 0, 75), 0)


class ExamTest(unittest.TestCase):

    def test_nearest_upcoming_exam_for_course(self):
        exams = [
            {"course": "CSE101", "date": "2026-10-01"},
            {"course": "MATH201", "date": "2026-09-01"},
            {"course": "MATH201", "date": "2026-12-01"},
        ]
        today = date(2026, 8, 15)
        self.assertEqual(course_exam(exams, "MATH201", today), date(2026, 9, 1))

    def test_past_exams_ignored(self):
        exams = [{"course": "MATH201", "date": "2026-07-01"}]
        self.assertIsNone(course_exam(exams, "MATH201", date(2026, 8, 15)))


class ReviewTest(unittest.TestCase):

    def test_last_reviewed_finds_latest(self):
        log = {"2026-07-30": ["CSE101|Arrays"],
               "2026-08-01": ["CSE101|Arrays", "CSE101|Linked Lists"]}
        self.assertEqual(last_reviewed(log, "CSE101", "Arrays"),
                         date(2026, 8, 1))

    def test_last_reviewed_none_when_absent(self):
        self.assertIsNone(last_reviewed({"2026-08-01": ["X|Y"]}, "CSE101", "Arrays"))


class NextActionsTest(unittest.TestCase):

    def test_overdue_beats_everything(self):
        today = date(2026, 8, 2)
        b = _broker()
        actions = next_actions(b, today)
        top = actions[0]
        self.assertEqual(top["kind"], "homework")
        self.assertEqual(top["course"], "CSE101")
        self.assertIn("OVERDUE", top["reason"])
        self.assertGreater(top["score"], 80)

    def test_study_action_near_exam_with_high_yield(self):
        today = date(2026, 11, 28)
        b = _broker()
        actions = next_actions(b, today)
        study = [a for a in actions if a["kind"] == "study"]
        self.assertTrue(study, actions)
        top = study[0]
        self.assertEqual(top["course"], "MATH201")
        self.assertIn("exam in", top["reason"])
        self.assertGreater(top["score"], 60)

    def test_attendance_risk_action_present(self):
        today = date(2026, 8, 2)
        b = _broker()
        att = [a for a in next_actions(b, today) if a["kind"] == "attendance"]
        self.assertEqual(len(att), 1)
        self.assertEqual(att[0]["course"], "CSE101")
        self.assertIn("50%", att[0]["reason"])

    def test_ranking_is_deterministic(self):
        today = date(2026, 8, 2)
        a = next_actions(_broker(), today)
        b = next_actions(_broker(), today)
        self.assertEqual([x["title"] for x in a], [x["title"] for x in b])
        scores = [x["score"] for x in a]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_done_homework_excluded(self):
        today = date(2026, 8, 2)
        b = _broker()
        b._data["homework"][0]["done"] = True
        actions = next_actions(b, today)
        self.assertNotIn("HW1", [a["title"] for a in actions])


class RevisionQueueTest(unittest.TestCase):

    def test_high_yield_due_after_interval(self):
        today = date(2026, 8, 2)  # reviewed 2026-08-01 -> 1 day, interval 3
        b = _broker()
        self.assertEqual(revision_due(b, today), [])
        # age it past the 3-day interval
        b._data["checklist.log"] = {"2026-07-29": ["CSE101|Arrays"]}
        due = revision_due(b, today)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["title"], "Arrays")
        self.assertEqual(due[0]["yield"], "high")

    def test_revision_only_for_completed_topics(self):
        today = date(2026, 8, 2)
        b = _broker()
        b._data["checklist.log"] = {"2026-07-29": ["CSE101|Linked Lists"]}
        self.assertEqual(revision_due(b, today), [])


if __name__ == "__main__":
    unittest.main()
