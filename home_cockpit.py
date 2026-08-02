# File Location: home_cockpit.py
# Academic & Life Command Center — Home Cockpit tab (Phase 3).
#
# Root dashboard aggregating every broker stream:
#   * KPI cards: CGPA, weekly attendance %, daily task completion
#   * Predictive Intelligence Alert Panel (fed by Phase 2 outputs)
#   * pyqtgraph charts (PlotWidget + BarGraphItem) that redraw whenever the
#     relevant broker section broadcasts a signal — no static/one-time plots.
#
# The tab is shape-agnostic about data sources that later phases (4-8) will
# fill: attendance statuses are counted wherever "present"/"absent" strings
# appear under attendance.records, daily goals from life.daily_goals, CGPA from
# profile.student.cgpa. When data is absent the cards show "—", never fake.

import re
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel,
    QDoubleSpinBox, QSpinBox, QPushButton, QGroupBox,
)

import pyqtgraph as pg

from styles import COLORS
from syllabus_tab import live_unstudied_topics

STATUS_ROLE = {"NOMINAL": "active", "WARNING": "predictive",
               "CRITICAL RISK": "risk"}

WEEKDAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _set_role(widget, role):
    """Set a dynamic role property ('' clears it) and repolish so QSS applies."""
    widget.setProperty("role", role or "")
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _date_weekday(key):
    """Return weekday in the README/focus-data convention (0=Sunday..6=Saturday)
    for ISO-ish date keys, else None."""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            # datetime.weekday() is Monday=0; shift to Sunday=0 to match
            # WEEKDAY_NAMES and the focus training data's day_of_week.
            return (datetime.strptime(str(key), fmt).weekday() + 1) % 7
        except ValueError:
            continue
    return None


def _scan_statuses(node, out):
    """Recursively count 'present'/'absent'/'cancelled' strings and, when the
    key is a date, bucket them by weekday. Survives any Phase 6 records shape."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and value.strip().lower() in \
                    ("present", "absent", "cancelled"):
                status = value.strip().lower()
                out.setdefault(status, 0)
                out[status] += 1
                wd = _date_weekday(key)
                if wd is not None:
                    bucket = out.setdefault("by_weekday", {}).setdefault(
                        wd, {"present": 0, "absent": 0, "cancelled": 0})
                    bucket[status] += 1
            else:
                _scan_statuses(value, out)
    elif isinstance(node, list):
        for item in node:
            _scan_statuses(item, out)


def _task_counts(goals):
    """Tolerant daily-goal tally for any Phase 7 shape."""
    done = total = 0
    if isinstance(goals, list):
        for goal in goals:
            if isinstance(goal, dict):
                status = str(goal.get("status", "")).lower()
                if goal.get("done") or goal.get("completed") or \
                        status in ("done", "completed"):
                    done += 1
                total += 1
    return done, total


class KpiCard(QFrame):
    """Compact panel card with a big monospace value + muted caption."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setProperty("panel", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)

        self.title_lbl = QLabel(title)
        self.title_lbl.setProperty("muted", True)
        self.value_lbl = QLabel("—")
        self.value_lbl.setProperty("mono", True)
        self.value_lbl.setStyleSheet("font-size: 24px; font-weight: 700;")
        self.sub_lbl = QLabel("")
        self.sub_lbl.setProperty("muted", True)

        layout.addWidget(self.title_lbl)
        layout.addWidget(self.value_lbl)
        layout.addWidget(self.sub_lbl)

    def set_value(self, value, sub="", role=None):
        self.value_lbl.setText(value)
        self.sub_lbl.setText(sub)
        _set_role(self.value_lbl, role)


def _style_plot(plot, title, ylabel):
    plot.setBackground(COLORS["bg_raised"])
    plot.setTitle(title, color=COLORS["text"])
    plot.showGrid(x=True, y=True, alpha=0.15)
    for axis in ("left", "bottom"):
        plot.getAxis(axis).setPen(pg.mkPen(COLORS["border"]))
        plot.getAxis(axis).setTextPen(pg.mkPen(COLORS["text_muted"]))
    plot.setLabel("left", ylabel, color=COLORS["text_muted"])
    plot.setMenuEnabled(False)


class HomeCockpitTab(QWidget):
    """Live root dashboard. Redraws on any broker update to the sections it
    aggregates (predictive, attendance, life, profile)."""

    def __init__(self, broker, engine=None, parent=None):
        super().__init__(parent)
        self.broker = broker
        self.engine = engine
        self.setProperty("panel", True)
        self._build_ui()
        self._refresh_all()
        broker.section_changed.connect(self._on_section_changed)

    # -------------------------------------------------------------- UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        header = QLabel("Home Cockpit")
        header.setProperty("role", "active")
        header.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(header)

        # ---- KPI cards
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(8)
        self.kpi_cgpa = KpiCard("CGPA")
        self.kpi_att = KpiCard("Weekly Attendance")
        self.kpi_tasks = KpiCard("Daily Tasks Done")
        for card in (self.kpi_cgpa, self.kpi_att, self.kpi_tasks):
            kpi_row.addWidget(card, 1)
        root.addLayout(kpi_row)

        # ---- predictive panel + focus chart
        middle = QHBoxLayout()
        middle.setSpacing(8)
        middle.addWidget(self._build_alert_panel(), 2)
        middle.addWidget(self._build_focus_plot(), 3)
        root.addLayout(middle, 1)

        # ---- weekly chart
        root.addWidget(self._build_weekly_plot(), 1)

    def _build_alert_panel(self):
        panel = QFrame()
        panel.setProperty("panel", True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        title = QLabel("Predictive Intelligence Alert Panel")
        title.setProperty("role", "active")
        title.setStyleSheet("font-weight: 700;")
        layout.addWidget(title)

        # grade deflection
        self.grade_badge = QLabel("N/A")
        self.grade_badge.setProperty("mono", True)
        self.grade_badge.setStyleSheet("font-weight: 700;")
        _set_role(self.grade_badge, "muted")
        self.grade_line = QLabel("")
        self.grade_line.setProperty("mono", True)
        layout.addWidget(self.grade_badge)
        layout.addWidget(self.grade_line)

        # focus window
        self.focus_line = QLabel("")
        self.focus_line.setProperty("mono", True)
        layout.addWidget(self.focus_line)

        # habit cascade
        self.habit_line = QLabel("")
        self.habit_line.setProperty("mono", True)
        layout.addWidget(self.habit_line)

        # ---- live prediction inputs
        box = QGroupBox("Refresh prediction with live inputs")
        grid = QGridLayout(box)
        grid.setContentsMargins(8, 4, 8, 8)
        grid.setSpacing(4)

        grid.addWidget(QLabel("Attendance %"), 0, 0)
        self.att_spin = QDoubleSpinBox()
        self.att_spin.setRange(0, 100)
        self.att_spin.setValue(80)
        self.att_spin.setSuffix(" %")
        grid.addWidget(self.att_spin, 0, 1)

        grid.addWidget(QLabel("Study / week (min)"), 1, 0)
        self.study_spin = QSpinBox()
        self.study_spin.setRange(0, 1680)
        self.study_spin.setValue(400)
        grid.addWidget(self.study_spin, 1, 1)

        grid.addWidget(QLabel("Unstudied high-priority topics"), 2, 0)
        self.topics_spin = QSpinBox()
        self.topics_spin.setRange(0, 20)
        self.topics_spin.setValue(2)
        grid.addWidget(self.topics_spin, 2, 1)

        grid.addWidget(QLabel("Habit days missed"), 3, 0)
        self.days_spin = QSpinBox()
        self.days_spin.setRange(0, 30)
        self.days_spin.setValue(0)
        grid.addWidget(self.days_spin, 3, 1)

        self.refresh_btn = QPushButton("Run prediction")
        self.refresh_btn.clicked.connect(self._on_refresh)
        if self.engine is None:
            self.refresh_btn.setEnabled(False)
            self.refresh_btn.setToolTip("Predictive engine unavailable")
        grid.addWidget(self.refresh_btn, 4, 0, 1, 2)

        self.topics_live_lbl = QLabel("")
        self.topics_live_lbl.setProperty("muted", True)
        self.topics_live_lbl.setWordWrap(True)
        grid.addWidget(self.topics_live_lbl, 5, 0, 1, 2)

        self.att_live_lbl = QLabel("")
        self.att_live_lbl.setProperty("muted", True)
        self.att_live_lbl.setWordWrap(True)
        grid.addWidget(self.att_live_lbl, 6, 0, 1, 2)

        self.study_live_lbl = QLabel("")
        self.study_live_lbl.setProperty("muted", True)
        self.study_live_lbl.setWordWrap(True)
        grid.addWidget(self.study_live_lbl, 7, 0, 1, 2)

        self.habit_live_lbl = QLabel("")
        self.habit_live_lbl.setProperty("muted", True)
        self.habit_live_lbl.setWordWrap(True)
        grid.addWidget(self.habit_live_lbl, 8, 0, 1, 2)

        layout.addWidget(box)
        layout.addStretch(1)
        return panel

    def _build_focus_plot(self):
        self.focus_plot = pg.PlotWidget()
        _style_plot(self.focus_plot, "Optimal focus profile (predicted)",
                    "productivity")
        self.focus_plot.setXRange(-0.5, 23.5)
        self.focus_plot.setLabel("bottom", "hour of day",
                                 color=COLORS["text_muted"])
        return self.focus_plot

    def _build_weekly_plot(self):
        self.weekly_plot = pg.PlotWidget()
        _style_plot(self.weekly_plot, "Weekly attendance rate", "% present")
        self.weekly_plot.setLabel("bottom", "day of week",
                                  color=COLORS["text_muted"])
        return self.weekly_plot

    # --------------------------------------------------- broker signals
    def _on_section_changed(self, section, _value):
        if section in ("predictive", "attendance", "life", "profile", "syllabus"):
            self._refresh_all()

    # ------------------------------------------------------------ refresh
    def _refresh_all(self):
        self._refresh_kpis()
        self._refresh_alerts()
        self._refresh_charts()

    def _refresh_kpis(self):
        # CGPA
        cgpa = self.broker.get("profile.student.cgpa")
        if cgpa is None:
            self.kpi_cgpa.set_value("—", "set in Profiles (Phase 4)")
        else:
            value = float(cgpa)
            self.kpi_cgpa.set_value(
                f"{value:.2f}", "out of 4.00",
                "active" if value >= 3.0 else "predictive")

        # attendance rate
        scan = {}
        _scan_statuses(self.broker.get("attendance.records", {}), scan)
        present, absent = scan.get("present", 0), scan.get("absent", 0)
        if present + absent == 0:
            self.kpi_att.set_value("—", "no records yet (Phase 6)")
        else:
            rate = 100.0 * present / (present + absent)
            self.kpi_att.set_value(
                f"{rate:.1f}%", f"{present} present / {present + absent} held",
                "active" if rate >= 75 else ("predictive" if rate >= 65 else "risk"))

        # daily tasks
        done, total = _task_counts(self.broker.get("life.daily_goals", []))
        if total == 0:
            self.kpi_tasks.set_value("—", "no goals yet (Phase 7)")
        else:
            pct = 100.0 * done / total
            self.kpi_tasks.set_value(
                f"{done}/{total}", f"{pct:.0f}% complete",
                "active" if pct >= 75 else ("predictive" if pct >= 40 else "risk"))

    def _refresh_alerts(self):
        predictive = self.broker.get("predictive", {}) or {}
        grade = predictive.get("grade_deflection", {}) or {}
        focus = predictive.get("focus_window", {}) or {}
        habit = predictive.get("habit_cascade", {}) or {}

        # grade deflection
        status, score = grade.get("status"), grade.get("predicted_score")
        if status and score is not None:
            self.grade_badge.setText(status)
            _set_role(self.grade_badge, STATUS_ROLE.get(status, "muted"))
            self.grade_line.setText(f"Predicted terminal score: {score:.1f} / 100")
        else:
            self.grade_badge.setText("NO PREDICTION")
            _set_role(self.grade_badge, "muted")
            self.grade_line.setText(grade.get("reason") or "unavailable")

        # focus window
        block, fscore = focus.get("best_block"), focus.get("score")
        if block:
            line = f"Optimal focus window: {block}"
            if fscore is not None:
                line += f"  (predicted {fscore:.1f})"
            self.focus_line.setText(line)
            _set_role(self.focus_line, "predictive")
        else:
            self.focus_line.setText("Focus model unavailable")
            _set_role(self.focus_line, "muted")

        # habit cascade
        state, rate = habit.get("state"), habit.get("failure_rate")
        if state:
            line = f"Habit cascade: {state}"
            if rate is not None:
                line += f"  ·  {100.0 * rate:.0f}% failure"
            self.habit_line.setText(line)
            _set_role(self.habit_line,
                      "risk" if state in ("HIGH", "CRITICAL INTERVENTION")
                      else "predictive")
        else:
            self.habit_line.setText("Habit cascade: no data")
            _set_role(self.habit_line, "muted")

        # live unstudied high-priority topics (from Syllabus Engine)
        has_syllabus = bool(self.broker.get("syllabus.semesters", {}))
        live = live_unstudied_topics(self.broker) if has_syllabus else None
        if live is not None:
            self.topics_live_lbl.setText(
                f"auto-synced from syllabus: {live} unstudied high-priority "
                "topic(s) — Run prediction uses this value")
            self.topics_spin.setValue(min(live, self.topics_spin.maximum()))
        else:
            self.topics_live_lbl.setText("no syllabus data yet — add/import in "
                                         "Syllabus Engine (Phase 5)")

        # live attendance rate (from Attendance Tracker)
        scan = {}
        _scan_statuses(self.broker.get("attendance.records", {}), scan)
        present, absent = scan.get("present", 0), scan.get("absent", 0)
        if present + absent == 0:
            self.att_live_lbl.setText("no attendance records yet — mark classes "
                                      "in Attendance Tracker (Phase 6)")
        else:
            rate = 100.0 * present / (present + absent)
            self.att_live_lbl.setText(
                f"auto-synced from attendance: {rate:.1f}% "
                f"({present}/{present + absent} classes) — Run prediction "
                "uses this value")
            self.att_spin.setValue(round(rate, 1))

        # live weekly study minutes + habit days missed (from Life tab)
        from life_tab import trailing_missed_days, weekly_study_minutes
        has_study = bool(self.broker.get("life.study_log", {}))
        if has_study:
            week = weekly_study_minutes(self.broker)
            self.study_live_lbl.setText(
                f"auto-synced from Life: {week} study min this week — "
                "Run prediction uses this value")
            self.study_spin.setValue(min(week, self.study_spin.maximum()))
        else:
            self.study_live_lbl.setText("no study-time log yet — track it in "
                                        "Life & Daily Goals (Phase 7)")
        has_habits = bool(self.broker.get("life.habits", {}))
        if has_habits:
            missed = trailing_missed_days(self.broker)
            self.habit_live_lbl.setText(
                f"auto-synced from Life: {missed} habit day(s) missed — "
                "Run prediction uses this value")
            self.days_spin.setValue(min(missed, self.days_spin.maximum()))
        else:
            self.habit_live_lbl.setText("no habits yet — add in Life & Daily "
                                        "Goals (Phase 7)")

    def _refresh_charts(self):
        self._plot_focus()
        self._plot_weekly()

    def _plot_focus(self):
        self.focus_plot.clear()
        profile = self.engine.hourly_profile() \
            if (self.engine and self.engine.focus_ready) else None
        if profile is None:
            self.focus_plot.setTitle(
                "Optimal focus profile — model unavailable",
                color=COLORS["text_muted"])
            return

        brushes = [COLORS["accent"]] * 24
        block = self.broker.get("predictive.focus_window.best_block") or ""
        match = re.match(r"(\d{2}):00", block)
        if match:
            start = int(match.group(1))
            brushes[start] = brushes[start + 1] = COLORS["predictive"]

        bars = pg.BarGraphItem(x=list(range(24)), height=list(profile),
                               width=0.75, brushes=brushes)
        self.focus_plot.addItem(bars)
        title = f"Optimal focus profile (predicted) — best {block}" if block \
            else "Optimal focus profile (predicted)"
        self.focus_plot.setTitle(title, color=COLORS["text"])

    def _plot_weekly(self):
        self.weekly_plot.clear()
        scan = {}
        _scan_statuses(self.broker.get("attendance.records", {}), scan)
        by_weekday = scan.get("by_weekday", {})
        if not by_weekday:
            self.weekly_plot.setTitle(
                "Weekly attendance — no records yet (Phase 6)",
                color=COLORS["text_muted"])
            return

        heights = []
        for wd in range(7):
            bucket = by_weekday.get(wd, {})
            held = bucket.get("present", 0) + bucket.get("absent", 0)
            heights.append(100.0 * bucket.get("present", 0) / held
                           if held else 0.0)
        bars = pg.BarGraphItem(x=list(range(7)), height=heights, width=0.7,
                               brush=COLORS["accent"])
        self.weekly_plot.addItem(bars)
        self.weekly_plot.getAxis("bottom").setTicks(
            [[(i, WEEKDAY_NAMES[i]) for i in range(7)]])
        self.weekly_plot.setYRange(0, 105)
        self.weekly_plot.setTitle("Weekly attendance rate", color=COLORS["text"])

    # ------------------------------------------------------------ actions
    def _on_refresh(self):
        if self.engine is None:
            return
        report = self.engine.predict_all(
            attendance_rate=self.att_spin.value() / 100.0,
            weekly_study_minutes=self.study_spin.value(),
            unstudied_topics=self.topics_spin.value(),
            days_missed=self.days_spin.value())
        self.broker.set_section("predictive", report)  # -> live redraw
