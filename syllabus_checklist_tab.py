# -*- coding: utf-8 -*-
"""Syllabus Checklist tab (Phase 11 — the "Today/Attendance/Marks" build's
Phase 3: syllabus-linked study checklist).

Per-subject collapsible cards list each course's syllabus topics as checkable
items; checking a topic marks it "Completed" in the syllabus itself (the same
field Syllabus Engine and Home Cockpit's live_unstudied_topics read), so
progress is a single source of truth.

  * Collapsible subject cards + a progress bar per subject.
  * Custom tasks (optional course link + optional due date), kept in the
    checklist section, not the syllabus.
  * Weekly heatmap: per-day completion counts for the last 13 weeks.
  * Streak counter: consecutive days with at least one completion.
  * Today Brief sync: today's pending custom tasks + today's-class topics are
    shown and toggled from the Today Brief "Tasks" column (same broker data).

New broker state introduced by this phase:
  * checklist.custom_tasks : [ {title, course, due_date, status} ]
  * checklist.log         : { "YYYY-MM-DD": [ "CODE|topic" | "custom|title", ... ] }
Topic completion state lives in the existing syllabus topic status field.
"""

from datetime import date, timedelta

from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QDateEdit, QLineEdit, QTableWidget, QTableWidgetItem,
    QFrame, QProgressBar, QListWidget, QListWidgetItem,
    QScrollArea, QDialog, QFormLayout, QCheckBox,
)

from styles import COLORS
from syllabus_tab import all_courses, semesters_map

HEAT_EMPTY = "#1A2230"
HEAT_LEVELS = ["#16324A", "#0E4A6B", "#0A6A8C", "#38A6FF"]
WEEKDAY_LETTERS = ["S", "M", "T", "W", "T", "F", "S"]


# ---------------------------------------------------------------------------
# Broker helpers (shared with Today Brief's Tasks column)
# ---------------------------------------------------------------------------
def day_completions(log, d):
    return (log or {}).get(d.isoformat(), [])


def log_add(log, date_str, entry):
    """Append a completion entry to a date bucket; dedupe. Returns new log."""
    log = dict(log or {})
    entries = list(log.get(date_str, []))
    if entry not in entries:
        entries.append(entry)
    log[date_str] = entries
    return log


def log_remove(log, date_str, entry):
    """Remove a completion entry; drop empty buckets. Returns new log."""
    log = dict(log or {})
    entries = list(log.get(date_str, []))
    if entry in entries:
        entries.remove(entry)
    if entries:
        log[date_str] = entries
    else:
        log.pop(date_str, None)
    return log


def current_streak(log, today=None):
    """Consecutive days ending today (or yesterday if today is still empty)
    that each have at least one completion."""
    today = today or date.today()
    log = log or {}
    day = today
    if not day_completions(log, day):
        day -= timedelta(days=1)
    streak = 0
    while day_completions(log, day):
        streak += 1
        day -= timedelta(days=1)
    return streak


def heatmap_data(log, today=None, weeks=13):
    """(col, row) -> (date, [completion entries]) for the last `weeks` full
    Sunday-starting weeks (rows Sun..Sat). Future days are empty."""
    today = today or date.today()
    log = log or {}
    sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    first = sunday - timedelta(days=(weeks - 1) * 7)
    cells = {}
    for w in range(weeks):
        week_start = first + timedelta(days=w * 7)
        for row in range(7):
            d = week_start + timedelta(days=row)
            entries = day_completions(log, d) if d <= today else []
            cells[(w, row)] = (d, entries)
    return cells


def topic_stats(broker):
    """(total, done) topics across the whole syllabus."""
    total = done = 0
    for _sem, _code, course in all_courses(broker):
        for topic in (course.get("topics", []) or []):
            if not isinstance(topic, dict):
                continue
            total += 1
            if str(topic.get("status", "")).lower() == "completed":
                done += 1
    return total, done


def today_task_items(broker, today=None):
    """Today's pending checklist items for the Today Brief Tasks column:
    pending custom tasks due today (or overdue / undated), plus pending
    syllabus topics of today's routine courses."""
    today = today or date.today()
    today_str = today.isoformat()
    items = []
    for task in (broker.get("checklist.custom_tasks", []) or []):
        if not isinstance(task, dict) or task.get("status") != "pending":
            continue
        due = task.get("due_date")
        if not due or due <= today_str:
            items.append({"kind": "task", "title": task.get("title", ""),
                          "course": task.get("course", "")})
    day = (today.weekday() + 1) % 7
    seen = set()
    for slot in (broker.get("attendance.routine", []) or []):
        if not isinstance(slot, dict) or slot.get("day") != day:
            continue
        code = slot.get("course")
        if not code or (code, day) in seen:
            continue
        seen.add((code, day))
        for sem, course in _course_locations(broker, code):
            for i, topic in enumerate(course.get("topics", []) or []):
                if not isinstance(topic, dict):
                    continue
                if str(topic.get("status", "")).lower() != "completed":
                    items.append({"kind": "topic", "sem": sem, "code": code,
                                  "index": i, "title": topic.get("name", ""),
                                  "course": code})
            break
    return items


def _course_locations(broker, code):
    """Yield (semester, course_dict) for every occurrence of a course code."""
    for sem, courses in semesters_map(broker).items():
        course = (courses or {}).get(code)
        if course:
            yield sem, course


def _heat_color(count):
    if count <= 0:
        return HEAT_EMPTY
    return HEAT_LEVELS[min(count - 1, len(HEAT_LEVELS) - 1)]


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------
class CustomTaskDialog(QDialog):
    def __init__(self, broker, parent=None, task=None):
        super().__init__(parent)
        self.setWindowTitle("Edit task" if task else "Add task")
        self.setMinimumWidth(360)
        task = task or {}
        form = QFormLayout(self)

        self.title = QLineEdit(task.get("title", ""))
        self.course = QComboBox()
        self.course.setEditable(True)
        codes = []
        for _sem, code, _course in all_courses(broker):
            if code not in codes:
                codes.append(code)
        for code in codes:
            self.course.addItem(code)
        self.course.lineEdit().setPlaceholderText("optional subject code")
        self.no_due = QCheckBox("No due date")
        self.no_due.setChecked(True)
        self.due = QDateEdit(QDate.currentDate())
        self.due.setCalendarPopup(True)

        form.addRow("Title", self.title)
        form.addRow("Subject", self.course)
        form.addRow(self.no_due)
        form.addRow("Due date", self.due)
        if task.get("course"):
            self.course.setCurrentText(task["course"])
        if task.get("due_date"):
            self.no_due.setChecked(False)
            self.due.setDate(QDate.fromString(task["due_date"], "yyyy-MM-dd"))
        self.due.setEnabled(not self.no_due.isChecked())
        self.no_due.toggled.connect(
            lambda on: self.due.setEnabled(not on))

        ok = QPushButton("Save")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addRow(row)

    def values(self):
        return {
            "title": self.title.text().strip(),
            "course": self.course.currentText().strip(),
            "due_date": (None if self.no_due.isChecked()
                         else self.due.date().toString("yyyy-MM-dd")),
        }


# ---------------------------------------------------------------------------
# Tab
# ---------------------------------------------------------------------------
class SyllabusChecklistTab(QWidget):
    def __init__(self, broker, parent=None):
        super().__init__(parent)
        self.broker = broker
        self._loading = False
        self._syncing = False
        self._cards = []
        self._heat_cells = {}
        self._build_ui()
        broker.section_changed.connect(self._on_section_changed)
        self._refresh()

    # -------------------------------------------------------------- UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        header = QLabel("Syllabus Checklist")
        header.setProperty("role", "active")
        header.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(header)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self._build_overview_card(), 0)
        top.addWidget(self._build_heatmap_card(), 1)
        root.addLayout(top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_box = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_box)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(6)
        self.scroll.setWidget(self.cards_box)
        root.addWidget(self.scroll, 1)

    def _build_overview_card(self):
        card = QFrame()
        card.setProperty("panel", True)
        card.setMinimumWidth(280)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        title = QLabel("Overview")
        title.setProperty("role", "active")
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        layout.addWidget(QLabel("Topic completion"))
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.progress_lbl = QLabel("")
        self.progress_lbl.setProperty("mono", True)
        layout.addWidget(self.progress_lbl)

        layout.addSpacing(6)
        layout.addWidget(QLabel("Current streak"))
        self.streak_lbl = QLabel("0")
        self.streak_lbl.setProperty("mono", True)
        self.streak_lbl.setStyleSheet("font-size: 26px; font-weight: 700;")
        layout.addWidget(self.streak_lbl)
        self.streak_sub = QLabel("consecutive days")
        self.streak_sub.setProperty("muted", True)
        layout.addWidget(self.streak_sub)

        self.today_lbl = QLabel("")
        self.today_lbl.setProperty("mono", True)
        layout.addWidget(self.today_lbl)
        layout.addStretch(1)
        return card

    def _build_heatmap_card(self):
        card = QFrame()
        card.setProperty("panel", True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        title = QLabel("Weekly heatmap — completions per day")
        title.setProperty("role", "active")
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        self.heatmap = QTableWidget(7, 13)
        self.heatmap.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.heatmap.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.heatmap.verticalHeader().setVisible(False)
        self.heatmap.horizontalHeader().setVisible(False)
        self.heatmap.verticalHeader().setDefaultSectionSize(18)
        self.heatmap.horizontalHeader().setDefaultSectionSize(22)
        self.heatmap.setFixedHeight(7 * 18 + 6)
        self.heatmap.cellClicked.connect(self._on_heat_clicked)
        for r, letter in enumerate(WEEKDAY_LETTERS):
            item = QTableWidgetItem(letter)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(QColor(COLORS["text_muted"]))
            self.heatmap.setVerticalHeaderItem(r, item)
        layout.addWidget(self.heatmap)

        self.heat_detail = QLabel("click a day to see what was completed")
        self.heat_detail.setProperty("muted", True)
        self.heat_detail.setWordWrap(True)
        layout.addWidget(self.heat_detail)
        return card

    def _build_subject_card(self, code):
        card = QFrame()
        card.setProperty("panel", True)
        card.code = code
        outer = QVBoxLayout(card)
        outer.setContentsMargins(10, 6, 10, 8)
        outer.setSpacing(4)

        header = QHBoxLayout()
        card.count_lbl = QLabel("")
        card.count_lbl.setProperty("mono", True)
        header.addWidget(card.count_lbl)
        card.bar = QProgressBar()
        card.bar.setRange(0, 100)
        card.bar.setFixedWidth(150)
        header.addWidget(card.bar)
        header.addStretch(1)
        toggle = QPushButton("▾")
        toggle.setCheckable(True)
        toggle.setChecked(True)
        header.addWidget(toggle)
        outer.addLayout(header)

        card.body = QWidget()
        body_layout = QVBoxLayout(card.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(2)
        card.topic_list = QListWidget()
        card.topic_list.itemChanged.connect(self._on_topic_toggled)
        body_layout.addWidget(card.topic_list)
        outer.addWidget(card.body)

        def toggle_body(checked):
            card.body.setVisible(checked)
            toggle.setText("▾" if checked else "▸")
        toggle.toggled.connect(toggle_body)

        self._cards.append((code, card))
        return card

    # --------------------------------------------------- broker signals
    def _on_section_changed(self, section, _value):
        if section in ("syllabus", "checklist") and not self._syncing:
            self._refresh()

    # ------------------------------------------------------------ refresh
    def _refresh(self):
        self._refresh_heatmap()
        self._refresh_overview()
        self._rebuild_cards()
        self._rebuild_custom_task_card()

    def _refresh_overview(self):
        total, done = topic_stats(self.broker)
        pct = int(100.0 * done / total) if total else 0
        self.progress.setValue(pct)
        if total:
            self.progress_lbl.setText(f"{done}/{total} topics  ({pct}%)")
        else:
            self.progress_lbl.setText("no syllabus topics yet — add courses in "
                                      "Syllabus Engine")
        log = self.broker.get("checklist.log", {}) or {}
        streak = current_streak(log)
        self.streak_lbl.setText(str(streak))
        self.streak_lbl.setProperty("role",
                                    "active" if streak >= 3
                                    else ("predictive" if streak else "muted"))
        self.streak_lbl.style().unpolish(self.streak_lbl)
        self.streak_lbl.style().polish(self.streak_lbl)
        n = len(day_completions(log, date.today()))
        self.today_lbl.setText(f"today: {n} completion(s)")

    def _refresh_heatmap(self):
        log = self.broker.get("checklist.log", {}) or {}
        cells = heatmap_data(log)
        self.heatmap.blockSignals(True)
        self.heatmap.setRowCount(7)
        self.heatmap.setColumnCount(13)
        for (w, r), (d, entries) in cells.items():
            item = self.heatmap.item(r, w)
            if item is None:
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.heatmap.setItem(r, w, item)
            n = len(entries)
            item.setBackground(QColor(_heat_color(n)))
            item.setToolTip(f"{d.isoformat()}" + (f" · {n} done" if n else ""))
            item.setData(Qt.ItemDataRole.UserRole, d.isoformat())
        self.heatmap.blockSignals(False)
        self._heat_cells = cells
        self.heat_detail.setText("click a day to see what was completed")

    def _rebuild_cards(self):
        self._loading = True
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._cards = []

        rows = [(code, list((course.get("topics", []) or [])))
                for _sem, code, course in all_courses(self.broker)]
        rows = [(code, topics) for code, topics in rows if topics]
        rows.sort(key=lambda rc: rc[0])

        if not rows:
            hint = QLabel("No syllabus topics yet — add courses in the "
                          "Syllabus Engine tab.")
            hint.setProperty("muted", True)
            self.cards_layout.addWidget(hint)
            self._loading = False
            return

        for code, topics in rows:
            card = self._build_subject_card(code)
            self.cards_layout.addWidget(card)
            self._fill_topic_list(card, topics)
        self._loading = False

    def _fill_topic_list(self, card, topics):
        card.topic_list.blockSignals(True)
        card.topic_list.clear()
        done = 0
        for i, topic in enumerate(topics):
            if not isinstance(topic, dict):
                continue
            name = topic.get("name", "")
            completed = str(topic.get("status", "")).lower() == "completed"
            if completed:
                done += 1
            label = ("● " if str(topic.get("yield", "")).lower() == "high"
                     else "○ ") + name
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if completed
                               else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, i)
            card.topic_list.addItem(item)
        card.topic_list.blockSignals(False)
        total = len(topics)
        pct = int(100.0 * done / total) if total else 0
        card.bar.setValue(pct)
        card.count_lbl.setText(f"{card.code}  ·  {done}/{total}")
        card.topic_list.setToolTip(
            "check a topic to mark it Completed in the syllabus")

    def _rebuild_custom_task_card(self):
        card = QFrame()
        card.setProperty("panel", True)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(10, 6, 10, 8)
        outer.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("Custom tasks")
        title.setProperty("role", "active")
        title.setStyleSheet("font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        for text, fn in (("+ Add", self._add_custom),
                         ("Edit", self._edit_custom),
                         ("Remove", self._remove_custom)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            header.addWidget(b)
        outer.addLayout(header)

        self.custom_list = QListWidget()
        self.custom_list.itemChanged.connect(self._on_custom_toggled)
        outer.addWidget(self.custom_list)
        self.cards_layout.addWidget(card)

        self._fill_custom_list()

    def _fill_custom_list(self):
        self.custom_list.blockSignals(True)
        self.custom_list.clear()
        today = date.today()
        tasks = [t for t in (self.broker.get("checklist.custom_tasks", []) or [])
                 if isinstance(t, dict)]
        tasks.sort(key=lambda t: (t.get("status") == "done",
                                  t.get("due_date") or "9999"))
        for t in tasks:
            done = t.get("status") == "done"
            course = f"  ({t['course']})" if t.get("course") else ""
            due = f"  ·  due {t['due_date']}" if t.get("due_date") else ""
            item = QListWidgetItem(f"{t.get('title', '')}{course}{due}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if done
                               else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, t.get("title"))
            item.setData(Qt.ItemDataRole.UserRole + 1, t.get("course"))
            if not done:
                due_d = t.get("due_date")
                if due_d:
                    try:
                        if date.fromisoformat(due_d) < today:
                            item.setForeground(QColor(COLORS["risk"]))
                            item.setText(f"⚠ OVERDUE — {item.text()}")
                        elif due_d == today.isoformat():
                            item.setForeground(QColor(COLORS["accent"]))
                    except (TypeError, ValueError):
                        pass
            self.custom_list.addItem(item)
        if not tasks:
            hint = QListWidgetItem("No custom tasks yet — add your own study "
                                   "tasks here")
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            hint.setForeground(QColor(COLORS["text_muted"]))
            self.custom_list.addItem(hint)
        self.custom_list.blockSignals(False)

    # ------------------------------------------------- topic / task toggles
    def _on_topic_toggled(self, item):
        if self._loading:
            return
        code = None
        for c, card in self._cards:
            if card.topic_list is item.listWidget():
                code = c
                break
        if code is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        checked = item.checkState() == Qt.CheckState.Checked
        self._set_topic_status(code, index, checked)

    def _set_topic_status(self, code, index, checked):
        for sem, course in _course_locations(self.broker, code):
            topics = list(course.get("topics", []) or [])
            if not (0 <= index < len(topics)) or not isinstance(
                    topics[index], dict):
                continue
            topics[index]["status"] = "Completed" if checked else "Pending"
            name = topics[index].get("name", "")
            today_str = date.today().isoformat()
            log = self.broker.get("checklist.log", {}) or {}
            entry = f"{code}|{name}"
            log = log_add(log, today_str, entry) if checked \
                else log_remove(log, today_str, entry)
            self._syncing = True
            try:
                self.broker.set_many({
                    f"syllabus.semesters.{sem}.{code}.topics": topics,
                    "checklist.log": log,
                })
            finally:
                self._syncing = False
            self._post_toggle()
            return

    def _on_custom_toggled(self, item):
        if self._loading:
            return
        title = item.data(Qt.ItemDataRole.UserRole)
        course = item.data(Qt.ItemDataRole.UserRole + 1)
        checked = item.checkState() == Qt.CheckState.Checked
        tasks = list(self.broker.get("checklist.custom_tasks", []) or [])
        changed = False
        for t in tasks:
            if isinstance(t, dict) and t.get("title") == title \
                    and t.get("course") == course:
                t["status"] = "done" if checked else "pending"
                changed = True
        if not changed:
            return
        today_str = date.today().isoformat()
        log = self.broker.get("checklist.log", {}) or {}
        entry = f"custom|{title}"
        log = log_add(log, today_str, entry) if checked \
            else log_remove(log, today_str, entry)
        self._syncing = True
        try:
            self.broker.set_many({
                "checklist.custom_tasks": tasks,
                "checklist.log": log,
            })
        finally:
            self._syncing = False
        self._post_toggle()

    def _post_toggle(self):
        self._refresh_overview()
        self._refresh_heatmap()
        for code, card in self._cards:
            self._refresh_card_progress(card)

    def _refresh_card_progress(self, card):
        done = total = 0
        for _sem, _code, course in all_courses(self.broker):
            if _code != card.code:
                continue
            for topic in (course.get("topics", []) or []):
                if not isinstance(topic, dict):
                    continue
                total += 1
                if str(topic.get("status", "")).lower() == "completed":
                    done += 1
        pct = int(100.0 * done / total) if total else 0
        card.bar.setValue(pct)
        card.count_lbl.setText(f"{card.code}  ·  {done}/{total}")

    # -------------------------------------------------- custom CRUD
    def _selected_custom(self):
        item = self.custom_list.currentItem()
        if item is None or not item.data(Qt.ItemDataRole.UserRole):
            return None, None
        return (item.data(Qt.ItemDataRole.UserRole),
                item.data(Qt.ItemDataRole.UserRole + 1))

    def _add_custom(self):
        dialog = CustomTaskDialog(self.broker, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values["title"]:
            return
        tasks = list(self.broker.get("checklist.custom_tasks", []) or [])
        tasks.append({**values, "status": "pending"})
        self.broker.set("checklist.custom_tasks", tasks)

    def _edit_custom(self):
        title, course = self._selected_custom()
        if title is None:
            return
        tasks = list(self.broker.get("checklist.custom_tasks", []) or [])
        idx = next((i for i, t in enumerate(tasks)
                    if isinstance(t, dict) and t.get("title") == title
                    and t.get("course") == course), None)
        if idx is None:
            return
        dialog = CustomTaskDialog(self.broker, self, task=tasks[idx])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values["title"]:
            return
        tasks[idx].update(values)
        self.broker.set("checklist.custom_tasks", tasks)

    def _remove_custom(self):
        title, course = self._selected_custom()
        if title is None:
            return
        tasks = [t for t in (self.broker.get("checklist.custom_tasks", []) or [])
                 if not (isinstance(t, dict) and t.get("title") == title
                         and t.get("course") == course)]
        self.broker.set("checklist.custom_tasks", tasks)

    # --------------------------------------------------- heatmap click
    def _on_heat_clicked(self, row, col):
        cell = getattr(self, "_heat_cells", {}).get((col, row))
        if not cell:
            return
        d, entries = cell
        if not entries:
            self.heat_detail.setText(f"{d.isoformat()} — nothing completed")
            return
        self.heat_detail.setText(
            f"{d.isoformat()} — " + ", ".join(entries))
