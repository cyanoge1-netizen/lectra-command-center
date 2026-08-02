# -*- coding: utf-8 -*-
"""Shared UI helpers (Phase A foundation).

Small, tab-agnostic widgets and guards so course codes stay consistent
across the whole graph (routine, homework, assignments, exams, checklist):
every dialog reads the same syllabus code list, normalizes to uppercase,
and warns before attaching data to a code that isn't in the syllabus yet.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QMessageBox


def course_codes(broker):
    """Sorted list of syllabus course codes (e.g. CSE101) in the graph."""
    codes = set()
    for semester in (broker.get("syllabus.semesters", {}) or {}).values():
        codes.update((semester or {}).keys())
    return sorted(codes)


def normalize_code(text):
    """Trim + uppercase a course code so typos don't fork the graph."""
    return (text or "").strip().upper()


def make_course_combo(broker):
    """An editable, auto-completing course-code combo seeded from the syllabus."""
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems(course_codes(broker))
    combo.lineEdit().setPlaceholderText("e.g. CSE101")
    completer = combo.completer()
    if completer is not None:
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
    return combo


def confirm_course_known(broker, parent, code):
    """True when a (normalized) code is known or the user chose to use it
    anyway. Guard against silently attaching data to a code that has no
    syllabus entry yet, which would orphan it from the topic graph."""
    code = normalize_code(code)
    if not code or code in course_codes(broker):
        return True
    ret = QMessageBox.question(
        parent,
        "Course not in syllabus",
        f"{code} isn't in your Syllabus yet.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if ret == QMessageBox.StandardButton.Yes:
        return True
    return False
