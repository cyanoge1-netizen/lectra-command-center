# -*- coding: utf-8 -*-
"""Life & Daily Goal Tracker (Phase 7).

Day-by-day tasks/goals with checkboxes, weekly habit check-ins, and a
historical study-time chart. Writes to the broker section `life` so the
Home Cockpit telemetry goes live:

  life.daily_goals : [ {date, title, status} ]      -> daily-tasks KPI
  life.habits      : { name: {enabled: true} }      -> habit list
  life.habit_log   : { name: {date: true} }         -> trailing missed days
  life.study_log   : { date: minutes }              -> weekly study minutes
"""
from datetime import datetime, timedelta

import pyqtgraph as pg

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QDateEdit, QSpinBox, QGroupBox,
    QInputDialog, QMessageBox, QFrame,
)

from home_cockpit import WEEKDAY_NAMES, _style_plot, _task_counts
from styles import COLORS

HABIT_LOG_MAX = 30  # trailing-day scan cap


def _week_dates(anchor):
    """7 dates (Sun=0 .. Sat) of the week containing `anchor` (QDate)."""
    monday = anchor.toPyDate() - timedelta(days=anchor.toPyDate().weekday())
    return [monday + timedelta(days=(wd + 6) % 7) for wd in range(7)]


def _monday(anchor):
    monday = anchor.toPyDate() - timedelta(days=anchor.toPyDate().weekday())
    return monday


def trailing_missed_days(broker, anchor=None):
    """Consecutive trailing days (ending today) where at least one enabled
    habit has no completed check-in."""
    if anchor is None:
        anchor = QDate.currentDate()
    habits = {name for name, spec in
              (broker.get("life.habits", {}) or {}).items()
              if (spec or {}).get("enabled", True)}
    if not habits:
        return 0
    log = broker.get("life.habit_log", {}) or {}
    if not any(log.get(name) for name in habits):
        return 0
    missed = 0
    d = anchor.toPyDate()
    while missed < HABIT_LOG_MAX:
        day_str = d.isoformat()
        if all(bool((log.get(name) or {}).get(day_str)) for name in habits):
            break
        missed += 1
        d -= timedelta(days=1)
    return missed


def weekly_study_minutes(broker, anchor=None):
    """Total logged study minutes in the week (Mon-Sun) containing `anchor`."""
    if anchor is None:
        anchor = QDate.currentDate()
    monday = _monday(anchor)
    log = broker.get("life.study_log", {}) or {}
    total = 0
    for i in range(7):
        d = (monday + timedelta(days=i)).isoformat()
        try:
            total += max(0, int(log.get(d, 0)))
        except (TypeError, ValueError):
            pass
    return total


class LifeTab(QWidget):
    def __init__(self, broker):
        super().__init__()
        self.broker = broker
        self._updating = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Date:"))
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        bar.addWidget(self.date_edit)
        self.today_btn = QPushButton("Today")
        bar.addWidget(self.today_btn)
        bar.addStretch(1)
        self.link_lbl = QLabel("")
        self.link_lbl.setProperty("mono", True)
        bar.addWidget(self.link_lbl)
        outer.addLayout(bar)

        row = QHBoxLayout()
        row.addWidget(self._build_goals_panel(), 1)
        row.addWidget(self._build_habits_panel(), 2)
        row.addWidget(self._build_study_panel(), 2)
        outer.addLayout(row, 1)

        self.today_btn.clicked.connect(
            lambda: self.date_edit.setDate(QDate.currentDate()))
        self.date_edit.dateChanged.connect(self._rebuild)
        self.broker.section_changed.connect(self._on_section_changed)
        self._rebuild()

    # --------------------------------------------------- panels
    def _build_goals_panel(self):
        panel = QFrame()
        panel.setProperty("panel", True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title = QLabel("Daily tasks & goals")
        title.setProperty("role", "active")
        layout.addWidget(title)
        self.goals_lbl = QLabel("")
        self.goals_lbl.setProperty("muted", True)
        layout.addWidget(self.goals_lbl)

        self.goals_list = QListWidget()
        layout.addWidget(self.goals_list, 1)

        add_row = QHBoxLayout()
        self.goal_input = QLineEdit()
        self.goal_input.setPlaceholderText("new task / goal…")
        self.goal_input.returnPressed.connect(self._add_goal)
        add_row.addWidget(self.goal_input, 1)
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._add_goal)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        del_btn = QPushButton("Remove selected")
        del_btn.clicked.connect(self._remove_goal)
        layout.addWidget(del_btn)

        self.goals_list.itemChanged.connect(self._on_goal_toggled)
        return panel

    def _build_habits_panel(self):
        panel = QFrame()
        panel.setProperty("panel", True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title = QLabel("Habits (weekly check-in)")
        title.setProperty("role", "active")
        layout.addWidget(title)
        self.habits_sum_lbl = QLabel("")
        self.habits_sum_lbl.setProperty("muted", True)
        self.habits_sum_lbl.setWordWrap(True)
        layout.addWidget(self.habits_sum_lbl)

        self.habits_table = QTableWidget(0, 7)
        self.habits_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.habits_table.verticalHeader().setDefaultSectionSize(30)
        self.habits_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.habits_table, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Add habit")
        add_btn.clicked.connect(self._add_habit)
        btn_row.addWidget(add_btn)
        del_btn = QPushButton("Remove selected")
        del_btn.clicked.connect(self._remove_habit)
        btn_row.addWidget(del_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        return panel

    def _build_study_panel(self):
        panel = QFrame()
        panel.setProperty("panel", True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title = QLabel("Study time (historical)")
        title.setProperty("role", "active")
        layout.addWidget(title)
        self.study_lbl = QLabel("")
        self.study_lbl.setProperty("muted", True)
        self.study_lbl.setWordWrap(True)
        layout.addWidget(self.study_lbl)

        entry = QHBoxLayout()
        self.study_spin = QSpinBox()
        self.study_spin.setRange(0, 1440)
        self.study_spin.setSuffix(" min")
        entry.addWidget(QLabel("Logged today/date:"))
        entry.addWidget(self.study_spin, 1)
        log_btn = QPushButton("Log")
        log_btn.clicked.connect(self._log_study)
        entry.addWidget(log_btn)
        layout.addLayout(entry)

        self.study_plot = pg.PlotWidget()
        _style_plot(self.study_plot, "Study minutes (last 14 days)", "min")
        layout.addWidget(self.study_plot, 1)

        self.week_lbl = QLabel("")
        self.week_lbl.setProperty("mono", True)
        layout.addWidget(self.week_lbl)
        return panel

    # --------------------------------------------------- broker signals
    def _on_section_changed(self, section, _value):
        if section == "life":
            self._rebuild()

    # ------------------------------------------------------------- rebuild
    def _rebuild(self):
        self._updating = True
        try:
            self._rebuild_goals()
            self._rebuild_habits()
            self._rebuild_study()
            self._refresh_link()
        finally:
            self._updating = False

    def _rebuild_goals(self):
        date_str = self.date_edit.date().toString(Qt.DateFormat.ISODate)
        goals = [g for g in (self.broker.get("life.daily_goals", []) or [])
                 if isinstance(g, dict) and g.get("date") == date_str]
        self.goals_list.clear()
        done = 0
        for g in goals:
            item = QListWidgetItem(g.get("title", ""))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if g.get("status") == "done"
                else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, g.get("title"))
            self.goals_list.addItem(item)
            if g.get("status") == "done":
                done += 1
        self.goals_lbl.setText(f"{done}/{len(goals)} done on {date_str}")

    def _rebuild_habits(self):
        dates = _week_dates(self.date_edit.date())
        habits = list((self.broker.get("life.habits", {}) or {}).keys())
        log = self.broker.get("life.habit_log", {}) or {}
        self.habits_table.setRowCount(len(habits))
        self.habits_table.setColumnCount(7)
        for ci, d in enumerate(dates):
            item = QTableWidgetItem(f"{WEEKDAY_NAMES[ci]}\n{d.isoformat()}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.habits_table.setHorizontalHeaderItem(ci, item)
        today = QDate.currentDate().toPyDate()
        for ri, name in enumerate(habits):
            self.habits_table.setVerticalHeaderItem(ri, QTableWidgetItem(name))
            for ci, d in enumerate(dates):
                day_str = d.isoformat()
                checkbox = QCheckBox()
                checkbox.setChecked(bool((log.get(name) or {}).get(day_str)))
                if d == today:
                    checkbox.setStyleSheet(
                        f"QCheckBox::indicator {{ border-color: "
                        f"{COLORS['accent']}; }}")
                checkbox.stateChanged.connect(
                    lambda _st, n=name, ds=day_str: self._on_habit_toggled(n, ds))
                wrapper = QWidget()
                wl = QHBoxLayout(wrapper)
                wl.setContentsMargins(0, 0, 0, 0)
                wl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                wl.addWidget(checkbox)
                self.habits_table.setCellWidget(ri, ci, wrapper)

        missed = trailing_missed_days(self.broker, self.date_edit.date())
        self.habits_sum_lbl.setText(
            f"{len(habits)} habit(s) · trailing missed days: {missed}")

    def _rebuild_study(self):
        dates = _week_dates(self.date_edit.date())
        today_str = self.date_edit.date().toString(Qt.DateFormat.ISODate)
        log = self.broker.get("life.study_log", {}) or {}
        logged = 0
        try:
            logged = max(0, int(log.get(today_str, 0)))
        except (TypeError, ValueError):
            pass
        self.study_spin.setValue(logged)
        self.study_lbl.setText(
            f"{logged} min logged on {today_str} — edit + Log to update.")

        window = [(datetime.today().date() - timedelta(days=i))
                  for i in range(13, -1, -1)]
        heights = []
        labels = []
        for d in window:
            try:
                heights.append(max(0, int(log.get(d.isoformat(), 0))))
            except (TypeError, ValueError):
                heights.append(0)
            labels.append(d.strftime("%m-%d"))
        self.study_plot.clear()
        bars = pg.BarGraphItem(x=list(range(len(window))), height=heights,
                               width=0.7, brush=COLORS["accent"])
        self.study_plot.addItem(bars)
        self.study_plot.getAxis("bottom").setTicks(
            [[(i, labels[i]) for i in range(0, len(labels), 3)]])
        self.study_plot.setYRange(0, max(30, max(heights) * 1.15))
        self.study_plot.setTitle("Study minutes (last 14 days)",
                                 color=COLORS["text"])

        week_total = weekly_study_minutes(self.broker, self.date_edit.date())
        self.week_lbl.setText(f"This week: {week_total} min")

    def _refresh_link(self):
        missed = trailing_missed_days(self.broker)
        week = weekly_study_minutes(self.broker)
        done, total = _task_counts(self.broker.get("life.daily_goals", []))
        parts = []
        if total:
            parts.append(f"tasks {done}/{total}")
        if self.broker.get("life.habits", {}):
            parts.append(f"missed {missed}d")
        if self.broker.get("life.study_log", {}):
            parts.append(f"week {week}min")
        self.link_lbl.setText("  ·  ".join(parts) or
                              "telemetry feeds Home Cockpit automatically")

    # ------------------------------------------------------------- actions
    def _add_goal(self):
        title = self.goal_input.text().strip()
        if not title:
            return
        goals = list(self.broker.get("life.daily_goals", []) or [])
        goals.append({
            "date": self.date_edit.date().toString(Qt.DateFormat.ISODate),
            "title": title,
            "status": "pending",
        })
        self.broker.set("life.daily_goals", goals)
        self.goal_input.clear()

    def _on_goal_toggled(self, item):
        if self._updating:
            return
        date_str = self.date_edit.date().toString(Qt.DateFormat.ISODate)
        goals = list(self.broker.get("life.daily_goals", []) or [])
        changed = False
        for g in goals:
            if isinstance(g, dict) and g.get("date") == date_str \
                    and g.get("title") == item.data(Qt.ItemDataRole.UserRole):
                new_status = ("done" if item.checkState()
                              == Qt.CheckState.Checked else "pending")
                if g.get("status") != new_status:
                    g["status"] = new_status
                    changed = True
        if changed:
            self.broker.set("life.daily_goals", goals)

    def _remove_goal(self):
        date_str = self.date_edit.date().toString(Qt.DateFormat.ISODate)
        sel = self.goals_list.currentItem()
        if sel is None:
            return
        title = sel.data(Qt.ItemDataRole.UserRole)
        goals = [g for g in (self.broker.get("life.daily_goals", []) or [])
                 if not (isinstance(g, dict) and g.get("date") == date_str
                         and g.get("title") == title)]
        self.broker.set("life.daily_goals", goals)

    def _add_habit(self):
        name, ok = QInputDialog.getText(self, "Add habit",
                                        "Habit name (e.g. Morning run):")
        name = name.strip()
        if not ok or not name:
            return
        habits = dict(self.broker.get("life.habits", {}) or {})
        habits[name] = {"enabled": True}
        self.broker.set("life.habits", habits)

    def _remove_habit(self):
        row = self.habits_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Remove habit",
                                    "Select a habit row first.")
            return
        name = self.habits_table.verticalHeaderItem(row).text()
        answer = QMessageBox.question(
            self, "Remove habit", f"Remove habit '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        habits = dict(self.broker.get("life.habits", {}) or {})
        habits.pop(name, None)
        log = dict(self.broker.get("life.habit_log", {}) or {})
        log.pop(name, None)
        self.broker.set_many({"life.habits": habits, "life.habit_log": log})

    def _on_habit_toggled(self, name, day_str):
        if self._updating:
            return
        log = dict(self.broker.get("life.habit_log", {}) or {})
        entry = dict(log.get(name, {}) or {})
        entry[day_str] = True
        log[name] = entry
        self.broker.set("life.habit_log", log)

    def _log_study(self):
        date_str = self.date_edit.date().toString(Qt.DateFormat.ISODate)
        log = dict(self.broker.get("life.study_log", {}) or {})
        log[date_str] = self.study_spin.value()
        self.broker.set("life.study_log", log)
