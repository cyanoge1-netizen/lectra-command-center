# -*- coding: utf-8 -*-
"""Attendance Tracker (Phase 6).

A weekly routine grid with mutable time/room slots and a 5/7-day view.
Click a class cell to cycle Present -> Absent -> Cancelled (right-click for
explicit options). Records live under attendance.records as
  { course_code: { "YYYY-MM-DD": "present"|"absent"|"cancelled", ... } }
which the Home Cockpit scanner already consumes for the KPI + weekly chart.

Routine schema (attendance.routine):
  [ { "day": 0-6 (Sun=0), "start": "HH:MM", "end": "HH:MM",
      "room": "C-101", "course": "CSE101" } ]
"""
from datetime import datetime, timedelta

from PyQt6.QtCore import QDate, QTime, Qt
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QDialog,
    QFormLayout, QLineEdit, QTimeEdit, QDateEdit, QMenu, QMessageBox,
)

from home_cockpit import WEEKDAY_NAMES, _scan_statuses

STATUS_ORDER = [None, "present", "absent", "cancelled"]
STATUS_BG = {
    "present": QColor("#1F4D2F"),
    "absent": QColor("#571F1F"),
    "cancelled": QColor("#2E333D"),
}
STATUS_FG = {
    "present": QColor("#C8F2D5"),
    "absent": QColor("#F2C8C8"),
    "cancelled": QColor("#AEB6C0"),
}
ACCENT = QColor("#38A6FF")
TEXT = QColor("#E1E8ED")


class ClassDialog(QDialog):
    """Add/edit one routine slot: course, start, end, room."""

    def __init__(self, broker, parent=None, slot=None):
        super().__init__(parent)
        self.setWindowTitle("Edit class" if slot else "Add class")
        self.setMinimumWidth(340)
        form = QFormLayout(self)

        self.course = QComboBox()
        self.course.setEditable(True)
        for code in _course_codes(broker):
            self.course.addItem(code)
        self.course.lineEdit().setPlaceholderText("e.g. CSE101")

        self.start = QTimeEdit(QTime(9, 0))
        self.start.setDisplayFormat("HH:mm")
        self.end = QTimeEdit(QTime(10, 0))
        self.end.setDisplayFormat("HH:mm")
        self.room = QLineEdit()
        self.room.setPlaceholderText("e.g. C-101")

        form.addRow("Course", self.course)
        form.addRow("Start", self.start)
        form.addRow("End", self.end)
        form.addRow("Room", self.room)

        if slot:
            self.course.setCurrentText(slot.get("course", ""))
            self.start.setTime(QTime.fromString(slot.get("start", "09:00"), "HH:mm"))
            self.end.setTime(QTime.fromString(slot.get("end", "10:00"), "HH:mm"))
            self.room.setText(slot.get("room", ""))

        ok = QPushButton("Save")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addRow(row)

    def slot(self, day):
        start = self.start.time().toString("HH:mm")
        end = self.end.time().toString("HH:mm")
        course = self.course.currentText().strip()
        if not course:
            return None
        return {
            "day": day,
            "start": start,
            "end": end,
            "room": self.room.text().strip(),
            "course": course,
        }


def _course_codes(broker):
    codes = []
    for semester in (broker.get("syllabus.semesters", {}) or {}).values():
        for code in (semester or {}).keys():
            if code not in codes:
                codes.append(code)
    return codes


def _date_for_weekday(anchor, weekday):
    """Date of `weekday` (Sun=0) in the week containing `anchor`."""
    monday = anchor.toPyDate() - timedelta(days=anchor.toPyDate().weekday())
    return monday + timedelta(days=(weekday + 6) % 7)


class AttendanceTab(QWidget):
    def __init__(self, broker):
        super().__init__()
        self.broker = broker
        self._slot_cache = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Mark attendance for:"))
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        bar.addWidget(self.date_edit)
        bar.addSpacing(16)
        bar.addWidget(QLabel("Routine view:"))
        self.days_combo = QComboBox()
        self.days_combo.addItem("7 days", 7)
        self.days_combo.addItem("5 days", 5)
        bar.addWidget(self.days_combo)
        bar.addStretch(1)
        self.add_btn = QPushButton("+ Add class")
        bar.addWidget(self.add_btn)
        self.clear_btn = QPushButton("Clear routine")
        bar.addWidget(self.clear_btn)
        outer.addLayout(bar)

        self.hint = QLabel("Click a class cell to cycle Present \u2192 Absent \u2192 "
                           "Cancelled; double-click to edit; right-click for options.")
        self.hint.setProperty("muted", True)
        outer.addWidget(self.hint)

        self.table = QTableWidget(0, 7)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setShowGrid(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        outer.addWidget(self.table, 1)

        legend = QHBoxLayout()
        legend.addWidget(_swatch("present", "Present"))
        legend.addWidget(_swatch("absent", "Absent"))
        legend.addWidget(_swatch("cancelled", "Cancelled"))
        legend.addStretch(1)
        self.stats_lbl = QLabel("")
        self.stats_lbl.setProperty("mono", True)
        legend.addWidget(self.stats_lbl)
        outer.addLayout(legend)

        self.date_edit.dateChanged.connect(self._rebuild)
        self.days_combo.currentIndexChanged.connect(self._on_days_changed)
        self.add_btn.clicked.connect(self._on_add)
        self.clear_btn.clicked.connect(self._on_clear_routine)
        self.table.itemClicked.connect(self._cycle_status)
        self.table.cellDoubleClicked.connect(self._on_cell_double)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

        self.broker.section_changed.connect(self._on_section_changed)
        self._rebuild()

    # --------------------------------------------------- broker signals
    def _on_section_changed(self, section, _value):
        if section == "attendance":
            self._rebuild()

    # ------------------------------------------------------------- data
    def _routine(self):
        return list(self.broker.get("attendance.routine", []) or [])

    def _records(self):
        return dict(self.broker.get("attendance.records", {}) or {})

    def _days_shown(self):
        n = self.broker.get("attendance.days_per_week", 5)
        return list(range(n))

    # ------------------------------------------------------------- grid
    def _rebuild(self):
        self._slot_cache = {}
        routine = self._routine()
        records = self._records()

        days = self._days_shown()
        dates = [_date_for_weekday(self.date_edit.date(), wd) for wd in days]
        today = QDate.currentDate().toPyDate()

        starts = sorted({s.get("start") for s in routine if s.get("start")})
        self.table.setColumnCount(len(days))
        self.table.setRowCount(len(starts))
        self.table.setVerticalHeaderLabels(starts)

        for ci, wd in enumerate(days):
            d = dates[ci]
            header = f"{WEEKDAY_NAMES[wd]}\n{d.isoformat()}"
            item = QTableWidgetItem(header)
            if d == today:
                item.setForeground(QBrush(ACCENT))
            self.table.setHorizontalHeaderItem(ci, item)

        for ri, start in enumerate(starts):
            for ci, wd in enumerate(days):
                slot = next((s for s in routine
                             if s.get("day") == wd and s.get("start") == start),
                            None)
                item = QTableWidgetItem("")
                if slot:
                    course = slot.get("course", "?")
                    date_str = dates[ci].isoformat()
                    status = (records.get(course, {}) or {}).get(date_str)
                    self._fill_cell(item, slot, status)
                    self._slot_cache[(ri, ci)] = slot
                item.setToolTip(
                    f"{slot.get('course')}  {start}–{slot.get('end')}  "
                    f"room {slot.get('room') or '—'}"
                    if slot else "double-click to add a class here")
                self.table.setItem(ri, ci, item)

        self._refresh_stats(records, dates)

    def _fill_cell(self, item, slot, status):
        lines = [slot.get("course", "?")]
        if slot.get("room"):
            lines.append(slot.get("room"))
        lines.append(f"\u25CF {status.capitalize()}" if status else "unmarked")
        item.setText("\n".join(lines))
        item.setForeground(QBrush(STATUS_FG.get(status, TEXT)))
        if status:
            item.setBackground(QBrush(STATUS_BG[status]))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    def _refresh_stats(self, records, dates):
        scan = {}
        _scan_statuses(records, scan)
        present, absent, cancelled = (
            scan.get("present", 0), scan.get("absent", 0), scan.get("cancelled", 0))
        held = present + absent
        rate = 100.0 * present / held if held else 0.0
        self.stats_lbl.setText(
            f"P {present}  A {absent}  C {cancelled}   |   held {held}   |   "
            f"{rate:.0f}%")

    # -------------------------------------------------- slot operations
    def _slot_at(self, row, col):
        return self._slot_cache.get((row, col))

    def _cycle_status(self, item):
        slot = self._slot_at(item.row(), item.column())
        if not slot:
            return
        date_str = _date_for_weekday(
            self.date_edit.date(), slot.get("day", 0)).isoformat()
        course = slot.get("course")
        records = self._records()
        current = (records.get(course, {}) or {}).get(date_str)
        nxt = STATUS_ORDER[(STATUS_ORDER.index(current) + 1) % len(STATUS_ORDER)]
        self._set_status(records, course, date_str, nxt)

    def _set_status(self, records, course, date_str, status):
        course_rec = dict(records.get(course, {}) or {})
        if status is None:
            course_rec.pop(date_str, None)
        else:
            course_rec[date_str] = status
        if course_rec:
            records[course] = course_rec
        else:
            records.pop(course, None)
        self.broker.set("attendance.records", records)

    def _on_cell_double(self, row, col):
        slot = self._slot_at(row, col)
        self._edit_class(slot, row, col)

    def _on_add(self):
        dialog = ClassDialog(self.broker, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._add_slot(dialog, None)

    def _edit_class(self, slot, row, col):
        if slot is not None:
            dialog = ClassDialog(self.broker, self, slot=slot)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self._remove_slot(slot.get("day"), slot.get("start"))
            day = slot.get("day")
            start = slot.get("start")
            self._add_slot(dialog, (day, start))
        else:
            start = self.table.verticalHeaderItem(row).text() if row >= 0 else None
            if start is None:
                return
            day = self._days_shown()[col] if 0 <= col < len(self._days_shown()) else None
            if day is None:
                return
            dialog = ClassDialog(self.broker, self)
            dialog.start.setTime(QTime.fromString(start, "HH:mm"))
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._add_slot(dialog, (day, start))

    def _add_slot(self, dialog, at):
        if at is not None:
            day, start = at
            slot = dialog.slot(day)
            if slot is None:
                return
            slot["start"] = start
        else:
            day = None
            slot = None
        if slot is None:
            QMessageBox.information(self, "No course",
                                    "A course code is required.")
            return
        routine = self._routine()
        existing = next((i for i, s in enumerate(routine)
                         if s.get("day") == slot["day"]
                         and s.get("start") == slot["start"]), None)
        if existing is not None:
            routine[existing] = slot
        else:
            routine.append(slot)
        self.broker.set("attendance.routine", routine)

    def _remove_slot(self, day, start):
        routine = [s for s in self._routine()
                   if not (s.get("day") == day and s.get("start") == start)]
        self.broker.set("attendance.routine", routine)

    def _on_clear_routine(self):
        if not self._routine():
            return
        answer = QMessageBox.question(
            self, "Clear routine",
            "Remove ALL classes from the routine? Attendance records are kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.broker.set("attendance.routine", [])

    def _on_days_changed(self, _index):
        self.broker.set("attendance.days_per_week",
                        self.days_combo.currentData())

    # --------------------------------------------------- context menu
    def _on_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if item is None:
            return
        slot = self._slot_at(item.row(), item.column())
        menu = QMenu(self)
        if slot:
            menu.addAction("Edit class...",
                           lambda: self._edit_class(
                               slot, item.row(), item.column()))
            menu.addAction("Delete class",
                           lambda: self._remove_slot(
                               slot.get("day"), slot.get("start")))
            menu.addSeparator()
            date_str = _date_for_weekday(
                self.date_edit.date(), slot.get("day", 0)).isoformat()
            records = self._records()
            current = (records.get(slot.get("course"), {}) or {}).get(date_str)
            for label, status in (("Present", "present"),
                                  ("Absent", "absent"),
                                  ("Cancelled", "cancelled")):
                action = menu.addAction(f"Mark {label}")
                action.setCheckable(True)
                action.setChecked(current == status)
                action.triggered.connect(
                    lambda _c, s=status: self._set_status(
                        self._records(), slot.get("course"), date_str, s))
            clear = menu.addAction("Clear status")
            clear.setEnabled(bool(current))
            clear.triggered.connect(
                lambda: self._set_status(
                    self._records(), slot.get("course"), date_str, None))
        else:
            menu.addAction("Add class here...",
                           lambda: self._on_cell_double(item.row(), item.column()))
        menu.exec(self.table.viewport().mapToGlobal(pos))


def _swatch(status, label):
    dot = QLabel("\u25CF")
    dot.setStyleSheet(f"color: {STATUS_FG[status].name()};")
    text = QLabel(label)
    text.setProperty("muted", True)
    row = QHBoxLayout()
    row.setSpacing(2)
    row.addWidget(dot)
    row.addWidget(text)
    holder = QWidget()
    holder.setLayout(row)
    return holder
