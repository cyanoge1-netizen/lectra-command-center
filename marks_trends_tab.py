# -*- coding: utf-8 -*-
"""Marks & Trends tab (Phase 2 of the "Today/Attendance/Marks" build).

Three linked widgets over the broker:

1. Attendance time-series graph (pyqtgraph). Cumulative % present over time
   for a single subject, or an all-subjects overlay. A crimson horizontal
   line marks the risk threshold (attendance.risk_threshold, default 75).
   Cancelled classes are ignored (not part of "held").

2. Editable marks table per subject. Components follow the Syllabus Engine
   schema (attendance / class_test / mid / final); totals come from the
   course's syllabus marks distribution, falling back to DEFAULT_TOTALS when
   no distribution is set. Obtained marks are editable and auto-saved to the
   broker `marks` section as { course: { component: obtained } }.

3. Arithmetic grade prediction. Straight mark arithmetic (no ML engine):
   standing % over entered components, projected % at a chosen % in the
   remaining components, the resulting letter grade (BD cutoffs), and a
   per-grade "needed % in remaining" table.

New broker state introduced by this phase:
  * marks                     : { course: { component: obtained } }
  * attendance.risk_threshold : int (percent), default 75
"""

from datetime import date

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame,
)

import pyqtgraph as pg

from styles import COLORS
from syllabus_tab import MARKS_LABELS
from home_cockpit import _style_plot

ALL_LABEL = "ALL SUBJECTS"
GRADE_CUTS = [("A+", 80), ("A", 70), ("A-", 60), ("B", 50),
              ("C", 40), ("D", 33)]
DEFAULT_TOTALS = {"attendance": 10, "class_test": 20, "mid": 30, "final": 40}
LINE_COLORS = ["#38A6FF", "#D9822B", "#6FE3A0", "#C77DFF", "#FFB86B", "#56C1C1"]


def _all_courses(broker):
    """Union of syllabus, attendance-record and marks course codes."""
    codes = []
    for semester in (broker.get("syllabus.semesters", {}) or {}).values():
        for code in (semester or {}).keys():
            if code not in codes:
                codes.append(code)
    for code in (broker.get("attendance.records", {}) or {}).keys():
        if code not in codes:
            codes.append(code)
    for code in (broker.get("marks", {}) or {}).keys():
        if code not in codes:
            codes.append(code)
    return codes


def _course_totals(broker, course):
    """Max marks per component from the syllabus, else DEFAULT_TOTALS."""
    totals = dict(DEFAULT_TOTALS)
    for semester in (broker.get("syllabus.semesters", {}) or {}).values():
        course_data = (semester or {}).get(course)
        if not course_data:
            continue
        marks = (course_data.get("marks") or {}) or {}
        if any(int(marks.get(key, 0)) > 0 for key, _ in MARKS_LABELS):
            for key, _ in MARKS_LABELS:
                if int(marks.get(key, 0)) > 0:
                    totals[key] = int(marks[key])
        break
    return totals


def _attendance_series(records, course):
    """Cumulative %-present series for one course.

    Returns (ordinals, rates) over dates with a present/absent record;
    cancelled classes are excluded from the running total.
    """
    rec = dict((records or {}).get(course, {}) or {})
    held = []
    for dstr, status in rec.items():
        status = str(status).strip().lower()
        if status not in ("present", "absent"):
            continue
        try:
            d = date.fromisoformat(str(dstr))
        except (TypeError, ValueError):
            continue
        held.append((d.toordinal(), 1 if status == "present" else 0))
    held.sort()
    ordinals, rates = [], []
    present = 0
    for i, (ordinal, val) in enumerate(held, 1):
        present += val
        ordinals.append(ordinal)
        rates.append(100.0 * present / i)
    return ordinals, rates


def grade_from_pct(pct):
    """(letter, role) for a percent under BD cutoffs. None -> ("—", "muted")."""
    if pct is None:
        return "—", "muted"
    for letter, cut in GRADE_CUTS:
        if pct >= cut:
            role = "active" if letter in ("A+", "A", "A-") \
                else ("predictive" if letter in ("B", "C") else "risk")
            return letter, role
    return "F", "risk"


def predict(course, marks, totals, expected_pct=75.0):
    """Arithmetic prediction for a course.

    Returns {entered_total, remaining_total, obtained_sum, standing_pct,
    projected_pct, needed{letter:(needed_pct, state)}, all_entered}.
    Obtained marks are clamped to their component total.
    """
    m = dict((marks or {}).get(course, {}) or {})
    obtained = {}
    for key, _ in MARKS_LABELS:
        val = m.get(key)
        if val is None or str(val).strip() == "":
            continue
        try:
            obtained[key] = float(val)
        except (TypeError, ValueError):
            continue

    grand_total = sum(totals.values())
    base = {"course": course, "totals": dict(totals),
            "entered_total": 0, "remaining_total": 0, "obtained_sum": 0.0,
            "standing_pct": None, "projected_pct": None,
            "needed": {}, "all_entered": True}
    if grand_total <= 0:
        return base

    entered_total = sum(totals[k] for k in obtained)
    obtained_sum = sum(min(obtained[k], totals[k]) for k in obtained)
    remaining_total = grand_total - entered_total
    standing_pct = (100.0 * obtained_sum / entered_total
                    if entered_total else None)
    projected_pct = ((obtained_sum + expected_pct / 100.0 * remaining_total)
                     / grand_total * 100.0)

    needed = {}
    for letter, cut in GRADE_CUTS:
        missing = cut / 100.0 * grand_total - obtained_sum
        if remaining_total > 0:
            need_pct = 100.0 * missing / remaining_total
            state = ("reached" if need_pct <= 0
                     else ("possible" if need_pct <= 100 else "impossible"))
            needed[letter] = (max(0.0, need_pct), state)
        else:
            state = ("reached" if standing_pct is not None
                     and standing_pct >= cut else "impossible")
            needed[letter] = (0.0, state)

    return {"course": course, "totals": dict(totals),
            "entered_total": entered_total, "remaining_total": remaining_total,
            "obtained_sum": obtained_sum, "standing_pct": standing_pct,
            "projected_pct": projected_pct, "needed": needed,
            "all_entered": remaining_total == 0}


def _date_ticks(ordinals):
    """~5 evenly spaced (ordinal, "dd MMM") ticks across the series."""
    if not ordinals:
        return []
    lo, hi = min(ordinals), max(ordinals)
    if hi == lo:
        return [(lo, date.fromordinal(lo).strftime("%d %b"))]
    step = max(1, (hi - lo) // 4)
    ticks = []
    ordinal = lo
    while ordinal <= hi:
        ticks.append((ordinal, date.fromordinal(ordinal).strftime("%d %b")))
        ordinal += step
    if ticks[-1][0] != hi:
        ticks.append((hi, date.fromordinal(hi).strftime("%d %b")))
    return ticks


class MarksTrendsTab(QWidget):
    def __init__(self, broker, parent=None):
        super().__init__(parent)
        self.broker = broker
        self._loading = False
        self._build_ui()
        broker.section_changed.connect(self._on_section_changed)
        self._refresh()

    # -------------------------------------------------------------- UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        header = QLabel("Marks & Trends")
        header.setProperty("role", "active")
        header.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(header)

        root.addWidget(self._build_trend_card(), 3)
        root.addWidget(self._build_marks_card(), 2)

    def _build_trend_card(self):
        card = QFrame()
        card.setProperty("panel", True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        row = QHBoxLayout()
        row.addWidget(QLabel("Attendance trend:"))
        self.subject_combo = QComboBox()
        row.addWidget(self.subject_combo)
        row.addSpacing(16)
        row.addWidget(QLabel("Risk threshold"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0, 100)
        self.threshold_spin.setSuffix(" %")
        row.addWidget(self.threshold_spin)
        row.addStretch(1)
        layout.addLayout(row)

        self.trend_plot = pg.PlotWidget()
        _style_plot(self.trend_plot, "Attendance trend", "% present")
        self.trend_plot.setLabel("bottom", "date", color=COLORS["text_muted"])
        self.trend_plot.setYRange(0, 105)
        layout.addWidget(self.trend_plot, 1)

        self.subject_combo.currentIndexChanged.connect(self._refresh)
        self.threshold_spin.valueChanged.connect(self._on_threshold_changed)
        return card

    def _build_marks_card(self):
        card = QFrame()
        card.setProperty("panel", True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        bar = QHBoxLayout()
        title = QLabel("Marks — edit obtained scores")
        title.setProperty("role", "active")
        title.setStyleSheet("font-weight: 600;")
        bar.addWidget(title)
        self.marks_course_combo = QComboBox()
        bar.addWidget(self.marks_course_combo)
        bar.addStretch(1)
        self.marks_hint = QLabel("")
        self.marks_hint.setProperty("muted", True)
        bar.addWidget(self.marks_hint)
        layout.addLayout(bar)
        self.marks_course_combo.currentIndexChanged.connect(self._refresh)

        two = QHBoxLayout()
        two.setSpacing(8)

        self.marks_table = QTableWidget(0, 4)
        self.marks_table.setHorizontalHeaderLabels(
            ["Component", "Total", "Obtained", "%"])
        self.marks_table.verticalHeader().setVisible(False)
        self.marks_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            self.marks_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self.marks_table.itemChanged.connect(self._on_marks_edited)
        two.addWidget(self.marks_table, 2)

        panel = QFrame()
        panel.setProperty("panel", True)
        p_layout = QVBoxLayout(panel)
        p_layout.setContentsMargins(12, 8, 12, 8)
        p_layout.setSpacing(4)
        p_title = QLabel("Prediction")
        p_title.setProperty("role", "active")
        p_title.setStyleSheet("font-weight: 600;")
        p_layout.addWidget(p_title)
        self.grade_lbl = QLabel("—")
        self.grade_lbl.setProperty("mono", True)
        self.grade_lbl.setStyleSheet("font-size: 30px; font-weight: 700;")
        p_layout.addWidget(self.grade_lbl)
        self.standing_lbl = QLabel("")
        self.standing_lbl.setProperty("mono", True)
        p_layout.addWidget(self.standing_lbl)
        self.projected_lbl = QLabel("")
        self.projected_lbl.setProperty("mono", True)
        p_layout.addWidget(self.projected_lbl)

        spin_row = QHBoxLayout()
        spin_row.addWidget(QLabel("Expected % in remaining:"))
        self.expected_spin = QDoubleSpinBox()
        self.expected_spin.setRange(0, 100)
        self.expected_spin.setValue(75)
        self.expected_spin.setSuffix(" %")
        spin_row.addWidget(self.expected_spin)
        spin_row.addStretch(1)
        p_layout.addLayout(spin_row)
        self.expected_spin.valueChanged.connect(self._refresh_prediction)

        self.need_table = QTableWidget(len(GRADE_CUTS), 2)
        self.need_table.setHorizontalHeaderLabels(["Grade", "Needed in remaining"])
        self.need_table.verticalHeader().setVisible(False)
        self.need_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.need_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.need_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        p_layout.addWidget(self.need_table, 1)
        two.addWidget(panel, 1)

        layout.addLayout(two, 1)
        return card

    # --------------------------------------------------- broker signals
    def _on_section_changed(self, section, _value):
        if section in ("attendance", "syllabus", "marks"):
            self._refresh()

    # ------------------------------------------------------------ refresh
    def _refresh(self, *_args):
        courses = _all_courses(self.broker)
        current = self.subject_combo.currentData()
        self.subject_combo.blockSignals(True)
        self.subject_combo.clear()
        if courses:
            self.subject_combo.addItem("All subjects", ALL_LABEL)
            for code in courses:
                self.subject_combo.addItem(code, code)
        else:
            self.subject_combo.addItem("— no courses —", None)
        if current is not None and current != "":
            idx = self.subject_combo.findData(current)
            if idx >= 0:
                self.subject_combo.setCurrentIndex(idx)
        self.subject_combo.blockSignals(False)

        self.marks_course_combo.blockSignals(True)
        self.marks_course_combo.clear()
        for code in courses:
            self.marks_course_combo.addItem(code, code)
        current_course = self.marks_course_combo.currentData()
        if current_course is not None and self.marks_course_combo.findData(
                current_course) < 0 and courses:
            self.marks_course_combo.setCurrentIndex(0)
        self.marks_course_combo.blockSignals(False)

        self.threshold_spin.blockSignals(True)
        self.threshold_spin.setValue(self.broker.get("attendance.risk_threshold", 75))
        self.threshold_spin.blockSignals(False)

        self._plot_trend()
        self._load_marks_table()

    # ------------------------------------------------------------ trend
    def _plot_trend(self):
        self.trend_plot.clear()
        records = self.broker.get("attendance.records", {}) or {}
        threshold = float(self.broker.get("attendance.risk_threshold", 75))

        threshold_line = pg.InfiniteLine(pos=threshold, angle=0,
                                         pen=pg.mkPen(COLORS["risk"], width=1))
        self.trend_plot.addItem(threshold_line)

        mode = self.subject_combo.currentData()
        courses = _all_courses(self.broker)
        if not courses:
            self.trend_plot.setTitle(
                "Attendance trend — no subjects yet", color=COLORS["text_muted"])
            return

        if mode == ALL_LABEL or mode is None:
            series = []
            for ci, code in enumerate(courses):
                xs, ys = _attendance_series(records, code)
                if not xs:
                    continue
                series.append((code, xs, ys, LINE_COLORS[ci % len(LINE_COLORS)]))
            if not series:
                self.trend_plot.setTitle(
                    "Attendance trend — no records yet", color=COLORS["text_muted"])
                return
            legend = self.trend_plot.addLegend(offset=(10, 10))
            for code, xs, ys, color in series:
                self.trend_plot.plot(xs, ys, pen=pg.mkPen(color, width=2),
                                     symbol="o", symbolSize=5,
                                     symbolBrush=pg.mkBrush(color))
                legend.addItem(
                    self.trend_plot.listDataItems()[-1], code)
            self._set_date_axis(xs)
            self.trend_plot.setTitle(
                "Attendance trend — all subjects", color=COLORS["text"])
        else:
            xs, ys = _attendance_series(records, mode)
            if not xs:
                self.trend_plot.setTitle(
                    f"Attendance trend — {mode}: no records yet",
                    color=COLORS["text_muted"])
                return
            self.trend_plot.plot(xs, ys, pen=pg.mkPen(COLORS["accent"], width=2),
                                 symbol="o", symbolSize=6,
                                 symbolBrush=pg.mkBrush(COLORS["accent"]))
            latest = ys[-1]
            label = f"Attendance trend — {mode}  ·  {latest:.0f}%"
            if latest < threshold:
                label += "  (below threshold)"
            self.trend_plot.setTitle(
                label, color=COLORS["risk"] if latest < threshold
                else COLORS["text"])
            self._set_date_axis(xs)

    def _set_date_axis(self, ordinals):
        ticks = _date_ticks(ordinals)
        self.trend_plot.getAxis("bottom").setTicks([ticks] if ticks else [])
        lo, hi = min(ordinals), max(ordinals)
        if hi > lo:
            self.trend_plot.setXRange(lo - 1, hi + 1)

    def _on_threshold_changed(self, value):
        self.broker.set("attendance.risk_threshold", round(value, 1))

    # -------------------------------------------------------------- marks
    def _load_marks_table(self):
        self._loading = True
        self.marks_table.setRowCount(0)
        course = self.marks_course_combo.currentData()
        if not course:
            self.marks_hint.setText("no courses yet")
            self._refresh_prediction()
            self._loading = False
            return
        totals = _course_totals(self.broker, course)
        obtained = (self.broker.get("marks", {}) or {}).get(course, {}) or {}
        self.marks_table.setRowCount(len(MARKS_LABELS))
        for ri, (key, label) in enumerate(MARKS_LABELS):
            total = totals[key]
            val = obtained.get(key)
            self.marks_table.setItem(ri, 0, _cell(label))
            self.marks_table.item(ri, 0).setFlags(
                Qt.ItemFlag.ItemIsEnabled)
            self.marks_table.setItem(ri, 1, _cell(str(total)))
            self.marks_table.item(ri, 1).setFlags(
                Qt.ItemFlag.ItemIsEnabled)
            obt_item = _cell("" if val is None or str(val).strip() == ""
                             else f"{float(val):g}")
            self.marks_table.setItem(ri, 2, obt_item)
            pct = 100.0 * min(float(val), total) / total \
                if val not in (None, "") and float(val) >= 0 else None
            self.marks_table.setItem(ri, 3, _cell("" if pct is None
                                                  else f"{pct:.0f}%"))
            self.marks_table.item(ri, 3).setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.marks_hint.setText(
            "totals from syllabus" if any(
                int((self.broker.get("syllabus.semesters", {}) or {}).get(
                    sem, {}).get(course, {}).get("marks", {}).get(k, 0))
                for sem in (self.broker.get("syllabus.semesters", {}) or {})
                for k, _ in MARKS_LABELS)
            else "default totals (set in Syllabus Engine)")
        self._loading = False
        self._refresh_prediction()

    def _on_marks_edited(self, item):
        if self._loading or item.column() != 2:
            return
        course = self.marks_course_combo.currentData()
        if not course:
            return
        key = MARKS_LABELS[item.row()][0]
        text = item.text().strip()
        marks = dict(self.broker.get("marks", {}) or {})
        course_marks = dict(marks.get(course, {}) or {})
        if text == "":
            course_marks.pop(key, None)
        else:
            try:
                course_marks[key] = float(text)
            except ValueError:
                return
        if course_marks:
            marks[course] = course_marks
        else:
            marks.pop(course, None)
        self.broker.set("marks", marks)

    # -------------------------------------------------------- prediction
    def _refresh_prediction(self):
        course = self.marks_course_combo.currentData()
        if not course:
            self.grade_lbl.setText("—")
            self.grade_lbl.setProperty("role", "muted")
            self.grade_lbl.style().unpolish(self.grade_lbl)
            self.grade_lbl.style().polish(self.grade_lbl)
            self.standing_lbl.setText("select a subject to predict")
            self.projected_lbl.setText("")
            self.need_table.setRowCount(0)
            return
        totals = _course_totals(self.broker, course)
        result = predict(course, self.broker.get("marks", {}), totals,
                         self.expected_spin.value())

        letter, role = grade_from_pct(result["projected_pct"])
        self.grade_lbl.setText(letter if result["projected_pct"] is not None else "—")
        self.grade_lbl.setProperty("role", role)
        self.grade_lbl.style().unpolish(self.grade_lbl)
        self.grade_lbl.style().polish(self.grade_lbl)

        if result["entered_total"] == 0:
            self.standing_lbl.setText("no marks entered yet")
            self.projected_lbl.setText(
                "enter obtained scores to predict your grade")
        else:
            self.standing_lbl.setText(
                f"standing {result['standing_pct']:.0f}% "
                f"({result['obtained_sum']:g}/{result['entered_total']} "
                f"marks so far)")
            if result["all_entered"]:
                self.projected_lbl.setText(
                    f"final {result['projected_pct']:.1f}% "
                    f"(all components entered)")
            else:
                self.projected_lbl.setText(
                    f"projected {result['projected_pct']:.1f}% at "
                    f"{self.expected_spin.value():.0f}% in the remaining "
                    f"{result['remaining_total']} marks")

        self.need_table.setRowCount(len(GRADE_CUTS))
        for ri, (letter, cut) in enumerate(GRADE_CUTS):
            need_pct, state = result["needed"].get(letter, (0.0, "impossible"))
            if result["entered_total"] == 0:
                cell_text = "—"
            elif state == "reached":
                cell_text = "already reached"
            elif state == "impossible":
                cell_text = "not possible"
            else:
                cell_text = f"\u2265 {need_pct:.0f}%"
            g_item = _cell(letter)
            n_item = _cell(cell_text)
            if state == "reached":
                color = COLORS["accent"]
            elif state == "impossible":
                color = COLORS["text_muted"]
            else:
                color = COLORS["text"]
            g_item.setForeground(QColor(color))
            n_item.setForeground(QColor(color))
            self.need_table.setItem(ri, 0, g_item)
            self.need_table.setItem(ri, 1, n_item)


def _cell(text):
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item
