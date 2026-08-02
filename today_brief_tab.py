# -*- coding: utf-8 -*-
"""Today Brief panel (Phase 1 of the "Today/Attendance/Marks" build).

Answers "what does today look like" at a glance: date + semester week +
exam countdown, today's effective routine with live status markers, a lab
status line, per-class material shortcuts, pending homework and assignments
(each with its own "No X today" line), and today's checklist (goals + habits
+ checklist tasks linked to the Syllabus Checklist tab).
Everything reads/writes the broker only.

Assumptions on the broker interface (verified against databroker.py):
  * get(dotted_key, default) / set(dotted_key, value) / set_many({})
  * section_changed(str) pyqtSignal broadcast on any mutation
New broker state introduced by this phase:
  * syllabus.semester_start  : "YYYY-MM-DD" or None
  * syllabus.exams           : [ {course, title, date, instructor} ]
  * homework                 : [ {course, title, due_date, done, instructor} ]
  * assignments              : [ {course, title, due_date, done, instructor} ]
  * attendance.overrides     : { date: { "COURSE|start": {"status": "cancelled"}
                                        | {"status": "moved", start, end, room} } }
Routine slots may carry an optional "type": "class"|"lab" (default "class")
and an optional "instructor"; the Attendance grid ignores these extra keys.
Material lookup convention: for a subject CODE, materials.courses[CODE].classes
is insertion-ordered (most recently added = last key); we take the last class
that has a non-empty notes_path/slides_path.
"""
import os
import re
import shutil
import subprocess
from datetime import date, datetime, timedelta

from PyQt6.QtCore import Qt, QDate, QTime, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QListWidget,
    QListWidgetItem, QCheckBox, QDialog, QFormLayout, QLineEdit, QComboBox,
    QTimeEdit, QDateEdit, QFileDialog, QMessageBox, QScrollArea,
)

from styles import COLORS
from ui_helpers import make_course_combo, normalize_code, confirm_course_known

DAY_INDEX = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
MARK = {"done": "\u2713", "in": "\u25CF", "up": "\u25CB", "cancelled": "\u2715"}


def sun0_index(d):
    return (d.weekday() + 1) % 7


def _time_now():
    return datetime.now().strftime("%H:%M")


def _status_for(start, end, now):
    if now >= end:
        return "done"
    if start <= now < end:
        return "in"
    return "up"


def _override_key(slot):
    return f"{slot.get('course')}|{slot.get('start')}"


def effective_slots(routine, overrides, date_str, day):
    """Weekly slots for `day`, with today-only overrides applied."""
    out = []
    for slot in routine:
        if not isinstance(slot, dict) or slot.get("day") != day:
            continue
        base = dict(slot)
        base.setdefault("type", "class")
        ov = (overrides.get(date_str) or {}).get(_override_key(base))
        if ov and ov.get("status") == "cancelled":
            base["overridden"] = "cancelled"
            out.append(base)
            continue
        if ov and ov.get("status") == "moved":
            base = dict(base)
            base["start"] = ov.get("start", base["start"])
            base["end"] = ov.get("end", base["end"])
            base["room"] = ov.get("room", base["room"])
            base["overridden"] = "moved"
        else:
            base["overridden"] = None
        out.append(base)
    out.sort(key=lambda s: s.get("start", ""))
    return out


def week_number(semester_start, today=None):
    """1-based week of the semester.

    Returns None if no start date is set, a negative number (days until
    start) when the semester has not started yet, or the whole week number
    (>= 1) once it has.
    """
    if not semester_start:
        return None
    today = today or date.today()
    try:
        start = date.fromisoformat(semester_start)
    except (TypeError, ValueError):
        return None
    days = (today - start).days
    if days < 0:
        return days
    return days // 7 + 1


def next_deadline(exams, homework, assignments, today=None):
    """Nearest upcoming exam/homework/assignment deadline. Returns dict or None."""
    today = today or date.today()
    candidates = []
    for exam in exams or []:
        try:
            d = date.fromisoformat(exam["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if d >= today:
            candidates.append((d, exam.get("title", "Exam"),
                               exam.get("course", ""), exam.get("instructor", "")))
    for hw in list(homework or []) + list(assignments or []):
        if hw.get("done"):
            continue
        try:
            d = date.fromisoformat(hw["due_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if d >= today:
            kind = "Assignment" if hw in (assignments or []) else "Homework"
            candidates.append((d, hw.get("title", kind),
                               hw.get("course", ""), hw.get("instructor", "")))
    if not candidates:
        return None
    d, title, course, instructor = min(candidates, key=lambda c: c[0])
    return {"days": (d - today).days, "title": title, "course": course,
            "instructor": instructor, "date": d}


def latest_material(materials, code):
    """Most recently added notes/slides for a subject code, or None."""
    course = (materials or {}).get(code)
    if not course:
        return None
    classes = course.get("classes", {}) or {}
    latest = None
    for title, cls in classes.items():
        cls = cls or {}
        if (cls.get("notes_path") or "").strip() or \
                (cls.get("slides_path") or "").strip():
            latest = {"class_title": title,
                      "notes_path": cls.get("notes_path", ""),
                      "slides_path": cls.get("slides_path", "")}
    return latest


def parse_routine_pdf(path):
    """Parse a routine.pdf via pdftotext into broker routine slots.

    Accepted row shape (one class per line):
        MON 09:00 - 10:00  CSE101  302  class
        mon 14:00-16:00 CSE102 Lab-2 lab
    Returns a list of {day, start, end, room, course, type} dicts.
    Raises ValueError if nothing parseable is found.
    """
    if shutil.which("pdftotext") is None:
        raise RuntimeError("pdftotext not installed (poppler-utils)")
    proc = subprocess.run(["pdftotext", "-layout", path, "-"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "pdftotext failed")
    pattern = re.compile(
        r"^(mon|tue|wed|thu|fri|sat|sun)\w*\s+(\d{1,2}):(\d{2})\s*[-]\s*"
        r"(\d{1,2}):(\d{2})\s+([A-Za-z0-9._-]+)\s+(.*)$", re.IGNORECASE)
    slots = []
    for line in proc.stdout.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        rest = m.group(7).strip()
        tokens = rest.split()
        type_ = "class"
        if tokens and tokens[-1].lower() in ("class", "lab"):
            type_ = tokens.pop().lower()
        room = " ".join(tokens)
        slots.append({
            "day": DAY_INDEX[m.group(1).lower()[:3]],
            "start": f"{int(m.group(2)):02d}:{m.group(3)}",
            "end": f"{int(m.group(4)):02d}:{m.group(5)}",
            "course": m.group(6).upper(),
            "room": room,
            "type": type_,
        })
    if not slots:
        raise ValueError("no routine rows recognised in PDF")
    return slots


class RoutineDialog(QDialog):
    def __init__(self, broker, parent=None, slot=None):
        super().__init__(parent)
        self.broker = broker
        self.setWindowTitle("Edit class" if slot else "Add class")
        self.setMinimumWidth(360)
        form = QFormLayout(self)
        slot = slot or {}
        self.course = make_course_combo(broker)
        self.type = QComboBox()
        self.type.addItems(["class", "lab"])
        self.start = QTimeEdit(QTime.fromString(slot.get("start", "09:00"), "HH:mm"))
        self.start.setDisplayFormat("HH:mm")
        self.end = QTimeEdit(QTime.fromString(slot.get("end", "10:00"), "HH:mm"))
        self.end.setDisplayFormat("HH:mm")
        self.room = QLineEdit(slot.get("room", ""))
        self.room.setPlaceholderText("e.g. 302")
        self.instructor = QLineEdit(slot.get("instructor", ""))
        self.instructor.setPlaceholderText("e.g. Prof. Karim")
        form.addRow("Subject", self.course)
        form.addRow("Type", self.type)
        form.addRow("Start", self.start)
        form.addRow("End", self.end)
        form.addRow("Room", self.room)
        form.addRow("Instructor", self.instructor)
        if slot.get("course"):
            self.course.setCurrentText(slot["course"])
        if slot.get("type") in ("class", "lab"):
            self.type.setCurrentText(slot["type"])
        ok = QPushButton("Save")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addRow(row)

    def accept(self):
        self.course.setCurrentText(normalize_code(self.course.currentText()))
        if not confirm_course_known(self.broker, self, self.course.currentText()):
            return
        super().accept()

    def values(self):
        return {
            "course": normalize_code(self.course.currentText()),
            "type": self.type.currentText(),
            "start": self.start.time().toString("HH:mm"),
            "end": self.end.time().toString("HH:mm"),
            "room": self.room.text().strip(),
            "instructor": self.instructor.text().strip(),
        }


class HomeworkDialog(QDialog):
    def __init__(self, broker, parent=None, hw=None, kind="homework"):
        super().__init__(parent)
        self.broker = broker
        kind_label = kind.capitalize()
        self.setWindowTitle(f"Edit {kind}" if hw else f"Add {kind}")
        self.setMinimumWidth(360)
        hw = hw or {}
        form = QFormLayout(self)
        self.course = make_course_combo(broker)
        self.title = QLineEdit(hw.get("title", ""))
        self.due = QDateEdit(QDate.fromString(hw.get("due_date") or "", "yyyy-MM-dd")
                             if hw.get("due_date") else QDate.currentDate())
        self.due.setCalendarPopup(True)
        self.instructor = QLineEdit(hw.get("instructor", ""))
        self.instructor.setPlaceholderText("e.g. Prof. Karim")
        form.addRow("Subject", self.course)
        form.addRow("Title", self.title)
        form.addRow("Due date", self.due)
        form.addRow("Instructor", self.instructor)
        if hw.get("course"):
            self.course.setCurrentText(hw["course"])
        ok = QPushButton("Save")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addRow(row)

    def accept(self):
        self.course.setCurrentText(normalize_code(self.course.currentText()))
        if not confirm_course_known(self.broker, self, self.course.currentText()):
            return
        super().accept()

    def values(self):
        return {
            "course": normalize_code(self.course.currentText()),
            "title": self.title.text().strip(),
            "due_date": self.due.date().toString("yyyy-MM-dd"),
            "instructor": self.instructor.text().strip(),
        }


class ExamsDialog(QDialog):
    def __init__(self, broker, parent=None):
        super().__init__(parent)
        self.broker = broker
        self.setWindowTitle("Exams & deadlines")
        self.setMinimumSize(420, 300)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        btn_row = QHBoxLayout()
        add = QPushButton("+ Add")
        add.clicked.connect(self._add)
        edit = QPushButton("Edit")
        edit.clicked.connect(self._edit)
        delete = QPushButton("Remove")
        delete.clicked.connect(self._remove)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for b in (add, edit, delete, close):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        self._reload()

    def _reload(self):
        self.list.clear()
        for exam in self.broker.get("syllabus.exams", []) or []:
            who = f" · {exam.get('instructor')}" if exam.get("instructor") else ""
            self.list.addItem(
                f"{exam.get('date')}  {exam.get('title')}  ({exam.get('course')}{who})")

    def _exams(self):
        return list(self.broker.get("syllabus.exams", []) or [])

    def _save(self, exams):
        self.broker.set("syllabus.exams", exams)

    def _add(self):
        exam = self._form()
        if not exam:
            return
        exams = self._exams()
        exams.append(exam)
        self._save(exams)
        self._reload()

    def _edit(self):
        row = self.list.currentRow()
        if row < 0:
            return
        exams = self._exams()
        exam = self._form(exams[row])
        if not exam:
            return
        exams[row] = exam
        self._save(exams)
        self._reload()

    def _remove(self):
        row = self.list.currentRow()
        if row < 0:
            return
        exams = self._exams()
        del exams[row]
        self._save(exams)
        self._reload()

    def _form(self, exam=None):
        exam = exam or {}
        dialog = QDialog(self)
        dialog.setWindowTitle("Exam / deadline")
        form = QFormLayout(dialog)
        course = make_course_combo(self.broker)
        title = QLineEdit(exam.get("title", ""))
        date_edit = QDateEdit(
            QDate.fromString(exam.get("date") or "", "yyyy-MM-dd")
            if exam.get("date") else QDate.currentDate())
        date_edit.setCalendarPopup(True)
        instructor = QLineEdit(exam.get("instructor", ""))
        instructor.setPlaceholderText("e.g. Prof. Karim")
        form.addRow("Subject", course)
        form.addRow("Title", title)
        form.addRow("Date", date_edit)
        form.addRow("Instructor", instructor)
        ok = QPushButton("Save")
        ok.clicked.connect(dialog.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dialog.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addRow(row)
        if exam.get("course"):
            course.setCurrentText(exam["course"])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        code = normalize_code(course.currentText())
        if not confirm_course_known(self.broker, dialog, code):
            return None
        return {"course": code,
                "title": title.text().strip(),
                "date": date_edit.date().toString("yyyy-MM-dd"),
                "instructor": instructor.text().strip()}


class TodayBriefTab(QWidget):
    def __init__(self, broker):
        super().__init__()
        self.broker = broker
        self._build_ui()
        QShortcut(QKeySequence("Ctrl+N"), self,
                  activated=lambda: self._add_entry("homework"))
        self.broker.section_changed.connect(self._on_section_changed)
        self._timer = QTimer(self)
        self._timer.setInterval(30000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    # ------------------------------------------------------------- layout
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(self._build_header_card(), 0)
        left.addWidget(self._build_routine_card(), 1)
        root.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(self._build_decisions_card(), 0)
        right.addWidget(self._build_materials_card(), 0)
        right.addWidget(self._build_homework_card(), 0)
        right.addWidget(self._build_checklist_card(), 1)
        root.addLayout(right, 2)

    def _card(self):
        card = QFrame()
        card.setProperty("panel", True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        return card, layout

    def _card_title(self, text, role="active"):
        label = QLabel(text)
        label.setProperty("role", role)
        label.setStyleSheet("font-weight: 600;")
        return label

    def _build_header_card(self):
        card, layout = self._card()
        layout.addWidget(self._card_title("Today"))
        self.date_lbl = QLabel("")
        self.date_lbl.setProperty("mono", True)
        self.date_lbl.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 26px; font-weight: 700;")
        layout.addWidget(self.date_lbl)
        self.subdate_lbl = QLabel("")
        self.subdate_lbl.setProperty("mono", True)
        self.subdate_lbl.setProperty("muted", True)
        layout.addWidget(self.subdate_lbl)
        self.week_lbl = QLabel("")
        self.week_lbl.setProperty("mono", True)
        layout.addWidget(self.week_lbl)
        self.countdown_lbl = QLabel("")
        self.countdown_lbl.setProperty("mono", True)
        self.countdown_lbl.setWordWrap(True)
        layout.addWidget(self.countdown_lbl)

        row = QHBoxLayout()
        self.start_btn = QPushButton("Set semester start")
        self.start_btn.clicked.connect(self._set_semester_start)
        self.exams_btn = QPushButton("Exams…")
        self.exams_btn.clicked.connect(self._manage_exams)
        row.addWidget(self.start_btn)
        row.addWidget(self.exams_btn)
        row.addStretch(1)
        layout.addLayout(row)
        return card

    def _build_routine_card(self):
        card, layout = self._card()
        layout.addWidget(self._card_title("Today's routine"))
        self.lab_lbl = QLabel("")
        self.lab_lbl.setProperty("mono", True)
        self.lab_lbl.setProperty("role", "predictive")
        layout.addWidget(self.lab_lbl)

        self.routine_table = QTableWidget(0, 6)
        self.routine_table.setHorizontalHeaderLabels(
            ["", "Time", "Subject", "Room", "Instructor", "Type"])
        self.routine_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.routine_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.routine_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.routine_table.verticalHeader().setVisible(False)
        self.routine_table.verticalHeader().setDefaultSectionSize(26)
        self.routine_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self.routine_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.routine_table, 1)

        edit_row = QHBoxLayout()
        for text, fn in (("Import routine PDF", self._import_pdf),
                         ("+ Add", self._add_class),
                         ("Edit", self._edit_class),
                         ("Remove", self._remove_class)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            edit_row.addWidget(b)
        layout.addLayout(edit_row)

        override_row = QHBoxLayout()
        hint = QLabel("today-only:")
        hint.setProperty("muted", True)
        override_row.addWidget(hint)
        for text, fn in (("Cancel today", self._cancel_today),
                         ("Move today", self._move_today),
                         ("Restore", self._restore_today)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            override_row.addWidget(b)
        override_row.addStretch(1)
        layout.addLayout(override_row)
        return card

    def _build_decisions_card(self):
        card, layout = self._card()
        layout.addWidget(self._card_title("Do this next"))
        self.decisions_lbl = QLabel("")
        self.decisions_lbl.setWordWrap(True)
        self.decisions_lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.decisions_lbl)
        self.revision_lbl = QLabel("")
        self.revision_lbl.setProperty("muted", True)
        self.revision_lbl.setWordWrap(True)
        layout.addWidget(self.revision_lbl)
        return card

    def _build_materials_card(self):
        card, layout = self._card()
        layout.addWidget(self._card_title("Class materials"))
        self.materials_table = QTableWidget(0, 3)
        self.materials_table.setHorizontalHeaderLabels(["Subject", "Notes", "Slides"])
        self.materials_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.materials_table.verticalHeader().setVisible(False)
        self.materials_table.verticalHeader().setDefaultSectionSize(28)
        self.materials_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.materials_table)
        return card

    def _build_homework_card(self):
        card, layout = self._card()
        layout.addWidget(self._card_title("Homework & assignments"))
        two = QHBoxLayout()
        two.setSpacing(10)

        hw_box = QVBoxLayout()
        hw_title = QLabel("Homework")
        hw_title.setProperty("muted", True)
        hw_box.addWidget(hw_title)
        self.hw_lbl = QLabel("")
        self.hw_lbl.setProperty("mono", True)
        hw_box.addWidget(self.hw_lbl)
        self.homework_list = QListWidget()
        hw_box.addWidget(self.homework_list, 1)
        hw_row = QHBoxLayout()
        for text, fn in (("+ Add", lambda: self._add_entry("homework")),
                         ("Edit", lambda: self._edit_entry("homework")),
                         ("Done", lambda: self._done_entry("homework")),
                         ("Remove", lambda: self._remove_entry("homework"))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            hw_row.addWidget(b)
        hw_box.addLayout(hw_row)
        two.addLayout(hw_box)

        asn_box = QVBoxLayout()
        asn_title = QLabel("Assignments")
        asn_title.setProperty("muted", True)
        asn_box.addWidget(asn_title)
        self.asn_lbl = QLabel("")
        self.asn_lbl.setProperty("mono", True)
        asn_box.addWidget(self.asn_lbl)
        self.assign_list = QListWidget()
        asn_box.addWidget(self.assign_list, 1)
        asn_row = QHBoxLayout()
        for text, fn in (("+ Add", lambda: self._add_entry("assignments")),
                         ("Edit", lambda: self._edit_entry("assignments")),
                         ("Done", lambda: self._done_entry("assignments")),
                         ("Remove", lambda: self._remove_entry("assignments"))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            asn_row.addWidget(b)
        asn_box.addLayout(asn_row)
        two.addLayout(asn_box)

        layout.addLayout(two, 1)
        return card

    def _build_checklist_card(self):
        card, layout = self._card()
        layout.addWidget(self._card_title("Today's checklist"))
        two = QHBoxLayout()
        goals_box = QVBoxLayout()
        goals_box.addWidget(QLabel("Goals"))
        self.goals_list = QListWidget()
        self.goals_list.itemChanged.connect(self._on_goal_toggled)
        goals_box.addWidget(self.goals_list, 1)
        two.addLayout(goals_box)
        habits_box = QVBoxLayout()
        habits_box.addWidget(QLabel("Habits"))
        self.habits_list = QListWidget()
        self.habits_list.itemChanged.connect(self._on_habit_toggled)
        habits_box.addWidget(self.habits_list, 1)
        two.addLayout(habits_box)
        tasks_box = QVBoxLayout()
        tasks_box.addWidget(QLabel("Tasks"))
        self.tasks_list = QListWidget()
        self.tasks_list.itemChanged.connect(self._on_task_toggled)
        tasks_box.addWidget(self.tasks_list, 1)
        two.addLayout(tasks_box)
        layout.addLayout(two, 1)
        return card

    # --------------------------------------------------- broker signals
    def _on_section_changed(self, section, _value):
        if section in ("attendance", "syllabus", "homework", "assignments",
                       "materials", "life", "checklist"):
            self._refresh()

    # ------------------------------------------------------------- refresh
    def _refresh(self):
        today = date.today()
        date_str = today.isoformat()
        day = sun0_index(today)
        now = _time_now()

        # header
        self.date_lbl.setText(today.strftime("%A").upper())
        self.subdate_lbl.setText(
            f"{today.strftime('%d')} · {today.strftime('%m')} · {today.year}")
        start = self.broker.get("syllabus.semester_start")
        week = week_number(start, today)
        if week is None:
            self.week_lbl.setText("Semester week: —  (set a start date)")
            self.week_lbl.setProperty("muted", True)
        elif week < 0:
            self.week_lbl.setText(
                f"Semester starts in {-week} day{'s' if -week != 1 else ''}")
            self.week_lbl.setProperty("muted", True)
        else:
            days_elapsed = (today - date.fromisoformat(start)).days
            day = days_elapsed % 7 + 1
            self.week_lbl.setText(
                f"WEEK {week} OF SEMESTER · day {day} of 7")
            self.week_lbl.setProperty("role", "active")
        self.week_lbl.style().unpolish(self.week_lbl)
        self.week_lbl.style().polish(self.week_lbl)

        deadline = next_deadline(
            self.broker.get("syllabus.exams", []),
            self.broker.get("homework", []),
            self.broker.get("assignments", []), today)
        if deadline is None:
            self.countdown_lbl.setText("No upcoming exams or deadlines")
            self.countdown_lbl.setStyleSheet(f"color: {COLORS['text_muted']};")
        elif deadline["days"] == 0:
            who = f" · {deadline['instructor']}" if deadline.get("instructor") else ""
            self.countdown_lbl.setText(
                f"⚠ TODAY: {deadline['title']} ({deadline['course']}{who})")
            self.countdown_lbl.setStyleSheet(f"color: {COLORS['risk']};")
        else:
            who = f" · {deadline['instructor']}" if deadline.get("instructor") else ""
            self.countdown_lbl.setText(
                f"{deadline['days']}d → {deadline['title']} ({deadline['course']}{who}) "
                f"· {deadline['date'].isoformat()}")
            self.countdown_lbl.setStyleSheet(f"color: {COLORS['accent']};")

        # routine + lab line
        self._render_routine(now, date_str, day)
        self._render_materials()
        self._render_homework(today)
        self._render_assignments(today)
        self._render_checklist(date_str)
        self._render_tasks()
        self._render_decisions(today)

    # -------------------------------------------------------- routine UI
    def _render_routine(self, now, date_str, day):
        routine = self.broker.get("attendance.routine", []) or []
        overrides = self.broker.get("attendance.overrides", {}) or {}
        slots = effective_slots(routine, overrides, date_str, day)
        self.routine_table.setRowCount(len(slots))
        labs = []
        for ri, slot in enumerate(slots):
            cancelled = slot.get("overridden") == "cancelled"
            status = "cancelled" if cancelled else \
                _status_for(slot["start"], slot["end"], now)
            mark = QTableWidgetItem(MARK[status])
            mark.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            mark.setForeground(QColor({
                "done": COLORS["text_muted"],
                "in": COLORS["accent"],
                "up": COLORS["text"],
                "cancelled": COLORS["risk"],
            }[status]))
            if cancelled:
                mark.setText("✕")
            time_item = QTableWidgetItem(
                f"{slot['start']}–{slot['end']}"
                + ("  ~" if slot.get("overridden") == "moved" else ""))
            time_item.setForeground(QColor(
                COLORS["text_muted"] if cancelled else COLORS["text"]))
            subject_item = QTableWidgetItem(slot.get("course", ""))
            subject_item.setForeground(QColor(
                COLORS["text_muted"] if cancelled else COLORS["text"]))
            room_item = QTableWidgetItem(slot.get("room", ""))
            room_item.setForeground(QColor(
                COLORS["text_muted"] if cancelled else COLORS["text"]))
            instructor_item = QTableWidgetItem(slot.get("instructor", ""))
            instructor_item.setForeground(QColor(
                COLORS["text_muted"] if cancelled else COLORS["text"]))
            type_item = QTableWidgetItem(
                slot.get("type", "class") + (" ✕" if cancelled else ""))
            type_item.setForeground(QColor(
                COLORS["risk"] if cancelled else COLORS["text_muted"]))
            for col, item in enumerate((mark, time_item, subject_item,
                                        room_item, instructor_item, type_item)):
                self.routine_table.setItem(ri, col, item)
            self.routine_table.item(ri, 0).setData(
                Qt.ItemDataRole.UserRole, _override_key(slot))
            if slot.get("type") == "lab" and not cancelled:
                labs.append(slot)
        if labs:
            lab = labs[0]
            who = f" · {lab['instructor']}" if lab.get("instructor") else ""
            self.lab_lbl.setText(
                f"Lab: {lab['course']} at {lab['start']}, Room {lab['room'] or '—'}{who}")
        else:
            self.lab_lbl.setText("No lab today")

    def _import_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import routine PDF", "", "PDF files (*.pdf)")
        if not path:
            return
        try:
            slots = parse_routine_pdf(path)
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        answer = QMessageBox.question(
            self, "Replace routine",
            f"Parsed {len(slots)} classes. Replace the recurring weekly "
            "routine?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.broker.set("attendance.routine", slots)
        QMessageBox.information(
            self, "Imported",
            f"Routine updated with {len(slots)} class(es). You can edit rows "
            "in this table; use Cancel/Move for today-only changes.")

    def _selected_slot(self):
        row = self.routine_table.currentRow()
        if row < 0:
            return None
        return self.routine_table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def _find_weekly_slot(self, key):
        routine = self.broker.get("attendance.routine", []) or []
        for slot in routine:
            if isinstance(slot, dict) and _override_key(slot) == key:
                return slot, routine
        return None, routine

    def _add_class(self):
        dialog = RoutineDialog(self.broker, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values["course"]:
            return
        routine = list(self.broker.get("attendance.routine", []) or [])
        slot = {"day": sun0_index(date.today()), **values}
        existing = next((i for i, s in enumerate(routine)
                         if isinstance(s, dict)
                         and s.get("day") == slot["day"]
                         and s.get("start") == slot["start"]
                         and s.get("course") == slot["course"]), None)
        if existing is not None:
            routine[existing] = slot
        else:
            routine.append(slot)
        self.broker.set("attendance.routine", routine)

    def _edit_class(self):
        key = self._selected_slot()
        if not key:
            QMessageBox.information(self, "Edit", "Select a class row first.")
            return
        slot, routine = self._find_weekly_slot(key)
        if slot is None:
            return
        dialog = RoutineDialog(self.broker, self, slot=slot)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values["course"]:
            return
        slot.update(values)
        self.broker.set("attendance.routine", routine)

    def _remove_class(self):
        key = self._selected_slot()
        if not key:
            QMessageBox.information(self, "Remove", "Select a class row first.")
            return
        routine = [s for s in (self.broker.get("attendance.routine", []) or [])
                   if not (isinstance(s, dict) and _override_key(s) == key)]
        self.broker.set("attendance.routine", routine)
        overrides = dict(self.broker.get("attendance.overrides", {}) or {})
        date_str = date.today().isoformat()
        day_map = dict(overrides.get(date_str, {}) or {})
        if key in day_map:
            del day_map[key]
            overrides[date_str] = day_map
            self.broker.set("attendance.overrides", overrides)

    def _cancel_today(self):
        key = self._selected_slot()
        if not key:
            return
        self._set_override(key, {"status": "cancelled"})

    def _move_today(self):
        key = self._selected_slot()
        if not key:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Move class (today only)")
        form = QFormLayout(dialog)
        start = QTimeEdit(QTime(10, 0))
        start.setDisplayFormat("HH:mm")
        end = QTimeEdit(QTime(11, 0))
        end.setDisplayFormat("HH:mm")
        room = QLineEdit()
        form.addRow("New start", start)
        form.addRow("New end", end)
        form.addRow("Room", room)
        ok = QPushButton("Move")
        ok.clicked.connect(dialog.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dialog.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addRow(row)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._set_override(key, {
            "status": "moved",
            "start": start.time().toString("HH:mm"),
            "end": end.time().toString("HH:mm"),
            "room": room.text().strip(),
        })

    def _restore_today(self):
        key = self._selected_slot()
        if not key:
            return
        overrides = dict(self.broker.get("attendance.overrides", {}) or {})
        date_str = date.today().isoformat()
        day_map = dict(overrides.get(date_str, {}) or {})
        if day_map.pop(key, None) is not None:
            if day_map:
                overrides[date_str] = day_map
            else:
                overrides.pop(date_str, None)
            self.broker.set("attendance.overrides", overrides)

    def _set_override(self, key, value):
        overrides = dict(self.broker.get("attendance.overrides", {}) or {})
        date_str = date.today().isoformat()
        day_map = dict(overrides.get(date_str, {}) or {})
        day_map[key] = value
        overrides[date_str] = day_map
        self.broker.set("attendance.overrides", overrides)

    # ------------------------------------------------- materials UI
    def _render_decisions(self, today):
        from decision_engine import next_actions, revision_due, KIND_ICON
        actions = next_actions(self.broker)
        muted = COLORS["text_muted"]
        if not actions:
            self.decisions_lbl.setText(
                f'<span style="color:{muted};">All clear — nothing is urgent '
                f"right now.</span>")
        else:
            rows = []
            for a in actions[:5]:
                if a["score"] >= 80:
                    color = COLORS["risk"]
                elif a["score"] >= 50:
                    color = COLORS["accent"]
                else:
                    color = muted
                icon = KIND_ICON.get(a["kind"], "\u2022")
                who = f" <span style='color:{muted}'>({a['course']})</span>" \
                    if a["course"] else ""
                rows.append(
                    f"<span style='color:{color}; font-weight:700;'>"
                    f"{a['score']}</span> &nbsp;<b>{icon} {a['title']}</b>"
                    f"{who} — {a['reason']}")
            self.decisions_lbl.setText("<br>".join(rows))

        due = revision_due(self.broker)
        high = sum(1 for d in due if d.get("yield") == "high")
        if due:
            self.revision_lbl.setText(
                f"\U0001F504 Revision queue: {len(due)} topic"
                f"{'s' if len(due) != 1 else ''} due"
                + (f" · {high} high-yield" if high else ""))
        else:
            self.revision_lbl.setText("No topics due for revision today")

    def _render_materials(self):
        date_str = date.today().isoformat()
        day = sun0_index(date.today())
        slots = effective_slots(
            self.broker.get("attendance.routine", []) or [],
            self.broker.get("attendance.overrides", {}) or {},
            date_str, day)
        materials = self.broker.get("materials.courses", {}) or {}
        subjects = []
        for slot in slots:
            course = slot.get("course")
            if slot.get("overridden") != "cancelled" and course and \
                    course not in subjects:
                subjects.append(course)
        self.materials_table.setRowCount(len(subjects))
        for ri, course in enumerate(subjects):
            item = QTableWidgetItem(course)
            self.materials_table.setItem(ri, 0, item)
            mat = latest_material(materials, course)
            for col, kind in ((1, "notes_path"), (2, "slides_path")):
                path = (mat or {}).get(kind, "") if mat else ""
                if path and os.path.exists(path):
                    label = os.path.basename(path)
                    button = QPushButton(label)
                    button.setFlat(True)
                    button.setStyleSheet(
                        f"color: {COLORS['accent']}; text-align: left;")
                    button.setToolTip(path)
                    button.clicked.connect(
                        lambda _c=False, p=path: _open_path(p))
                else:
                    button = QPushButton("—")
                    button.setFlat(True)
                    button.setEnabled(False)
                self.materials_table.setCellWidget(ri, col, button)

    # ------------------------------------------- homework / assignment UI
    def _render_entries(self, key, list_widget, lbl, today, plural):
        list_widget.clear()
        entries = [e for e in (self.broker.get(key, []) or [])
                   if isinstance(e, dict) and not e.get("done")]
        entries.sort(key=lambda e: e.get("due_date", ""))
        due_today = overdue = 0
        for e in entries:
            due = e.get("due_date", "")
            who = f" · {e.get('instructor')}" if e.get("instructor") else ""
            item = QListWidgetItem(
                f"{e.get('title')}  ({e.get('course')}){who}  ·  due {due}")
            item.setData(Qt.ItemDataRole.UserRole, e.get("title"))
            item.setData(Qt.ItemDataRole.UserRole + 1, e.get("course"))
            is_overdue = False
            try:
                is_overdue = date.fromisoformat(due) < today
            except (TypeError, ValueError):
                pass
            if is_overdue:
                overdue += 1
                item.setForeground(QColor(COLORS["risk"]))
                item.setText(f"⚠ OVERDUE — {item.text()}")
            elif due == today.isoformat():
                due_today += 1
                item.setForeground(QColor(COLORS["accent"]))
            list_widget.addItem(item)
        if not entries:
            list_widget.addItem(f"No pending {plural}")
            list_widget.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
        if due_today:
            lbl.setText(f"{due_today} {plural} due today")
            lbl.setStyleSheet(f"color: {COLORS['accent']};")
        elif overdue:
            lbl.setText(f"{overdue} overdue {plural}")
            lbl.setStyleSheet(f"color: {COLORS['risk']};")
        else:
            lbl.setText(f"No {plural} today")
            lbl.setStyleSheet(f"color: {COLORS['text_muted']};")

    def _render_homework(self, today):
        self._render_entries("homework", self.homework_list, self.hw_lbl,
                             today, "homework")

    def _render_assignments(self, today):
        self._render_entries("assignments", self.assign_list, self.asn_lbl,
                             today, "assignments")

    def _list_for(self, key):
        return self.homework_list if key == "homework" else self.assign_list

    def _selected_entry(self, widget):
        item = widget.currentItem()
        if item is None or not item.data(Qt.ItemDataRole.UserRole):
            return None, None
        return (item.data(Qt.ItemDataRole.UserRole),
                item.data(Qt.ItemDataRole.UserRole + 1))

    def _add_entry(self, key):
        kind = "assignment" if key == "assignments" else "homework"
        dialog = HomeworkDialog(self.broker, self, kind=kind)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values["title"]:
            return
        entries = list(self.broker.get(key, []) or [])
        entries.append({**values, "done": False})
        self.broker.set(key, entries)

    def _edit_entry(self, key):
        widget = self._list_for(key)
        title, course = self._selected_entry(widget)
        if title is None:
            return
        entries = list(self.broker.get(key, []) or [])
        idx = next((i for i, e in enumerate(entries)
                    if e.get("title") == title and e.get("course") == course), None)
        if idx is None:
            return
        kind = "assignment" if key == "assignments" else "homework"
        dialog = HomeworkDialog(self.broker, self, hw=entries[idx], kind=kind)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        entries[idx].update(dialog.values())
        self.broker.set(key, entries)

    def _done_entry(self, key):
        widget = self._list_for(key)
        title, course = self._selected_entry(widget)
        if title is None:
            return
        entries = list(self.broker.get(key, []) or [])
        for e in entries:
            if e.get("title") == title and e.get("course") == course:
                e["done"] = True
        self.broker.set(key, entries)

    def _remove_entry(self, key):
        widget = self._list_for(key)
        title, course = self._selected_entry(widget)
        if title is None:
            return
        entries = [e for e in (self.broker.get(key, []) or [])
                   if not (e.get("title") == title and e.get("course") == course)]
        self.broker.set(key, entries)

    # ------------------------------------------------- checklist UI
    def _render_checklist(self, date_str):
        # goals
        self.goals_list.blockSignals(True)
        self.goals_list.clear()
        goals = [g for g in (self.broker.get("life.daily_goals", []) or [])
                 if isinstance(g, dict) and g.get("date") == date_str]
        for g in goals:
            item = QListWidgetItem(g.get("title", ""))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked
                               if g.get("status") == "done"
                               else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, g.get("title"))
            self.goals_list.addItem(item)
        if not goals:
            self.goals_list.addItem("No goals set for today (add in Life tab)")
            self.goals_list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
        self.goals_list.blockSignals(False)

        # habits
        self.habits_list.blockSignals(True)
        self.habits_list.clear()
        habits = list((self.broker.get("life.habits", {}) or {}).keys())
        log = self.broker.get("life.habit_log", {}) or {}
        for name in habits:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if bool((log.get(name) or {}).get(date_str))
                else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.habits_list.addItem(item)
        if not habits:
            self.habits_list.addItem("No habits (add in Life tab)")
            self.habits_list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
        self.habits_list.blockSignals(False)

    def _render_tasks(self):
        from syllabus_checklist_tab import today_task_items
        self.tasks_list.blockSignals(True)
        self.tasks_list.clear()
        items = today_task_items(self.broker)
        for it in items:
            label = it["title"]
            if it.get("course"):
                label += f"  ({it['course']})"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, it)
            if it["kind"] == "topic":
                item.setForeground(QColor(COLORS["predictive"]))
            self.tasks_list.addItem(item)
        if not items:
            self.tasks_list.addItem("No pending checklist items today")
            self.tasks_list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
        self.tasks_list.blockSignals(False)

    def _on_task_toggled(self, item):
        from syllabus_checklist_tab import log_add, log_remove
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        checked = item.checkState() == Qt.CheckState.Checked
        today_str = date.today().isoformat()
        log = self.broker.get("checklist.log", {}) or {}
        if data["kind"] == "task":
            tasks = list(self.broker.get("checklist.custom_tasks", []) or [])
            changed = False
            for t in tasks:
                if isinstance(t, dict) and t.get("title") == data["title"] \
                        and t.get("course") == data["course"]:
                    t["status"] = "done" if checked else "pending"
                    changed = True
            if not changed:
                return
            entry = f"custom|{data['title']}"
            log = log_add(log, today_str, entry) if checked \
                else log_remove(log, today_str, entry)
            self.broker.set_many({"checklist.custom_tasks": tasks,
                                  "checklist.log": log})
        elif data["kind"] == "topic":
            sem, code, index = data["sem"], data["code"], data["index"]
            course = self.broker.get(
                f"syllabus.semesters.{sem}.{code}", {}) or {}
            topics = list(course.get("topics", []) or [])
            if not (0 <= index < len(topics)):
                return
            topics[index]["status"] = "Completed" if checked else "Pending"
            entry = f"{code}|{data['title']}"
            log = log_add(log, today_str, entry) if checked \
                else log_remove(log, today_str, entry)
            self.broker.set_many({
                f"syllabus.semesters.{sem}.{code}.topics": topics,
                "checklist.log": log,
            })

    def _on_goal_toggled(self, item):
        date_str = date.today().isoformat()
        title = item.data(Qt.ItemDataRole.UserRole)
        goals = list(self.broker.get("life.daily_goals", []) or [])
        changed = False
        for g in goals:
            if isinstance(g, dict) and g.get("date") == date_str \
                    and g.get("title") == title:
                status = ("done" if item.checkState() == Qt.CheckState.Checked
                          else "pending")
                if g.get("status") != status:
                    g["status"] = status
                    changed = True
        if changed:
            self.broker.set("life.daily_goals", goals)

    def _on_habit_toggled(self, item):
        date_str = date.today().isoformat()
        name = item.data(Qt.ItemDataRole.UserRole)
        log = dict(self.broker.get("life.habit_log", {}) or {})
        entry = dict(log.get(name, {}) or {})
        if item.checkState() == Qt.CheckState.Checked:
            entry[date_str] = True
        else:
            entry.pop(date_str, None)
        if entry:
            log[name] = entry
        else:
            log.pop(name, None)
        self.broker.set("life.habit_log", log)

    # ---------------------------------------------------------- dialogs
    def _set_semester_start(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Semester start date")
        form = QFormLayout(dialog)
        current = self.broker.get("syllabus.semester_start")
        date_edit = QDateEdit(
            QDate.fromString(current, "yyyy-MM-dd") if current
            else QDate.currentDate())
        date_edit.setDisplayFormat("yyyy-MM-dd")
        date_edit.setCalendarPopup(True)
        form.addRow("Start date", date_edit)
        ok = QPushButton("Save")
        ok.clicked.connect(dialog.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dialog.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addRow(row)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.broker.set("syllabus.semester_start",
                            date_edit.date().toString("yyyy-MM-dd"))

    def _manage_exams(self):
        ExamsDialog(self.broker, self).exec()


def _open_path(path):
    subprocess.Popen(["xdg-open", path],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
