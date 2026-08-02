# File Location: syllabus_tab.py
# Academic & Life Command Center — Syllabus Engine & Subject Hub (Phase 5).
#
# Schema (contract from the phase spec), stored under broker syllabus.semesters:
#   {semester: {course_code: {
#       "priority": "HIGH|MEDIUM|LOW", "status": "Pending|Studying|Revision|Completed",
#       "credits": int, "theory_hours": int, "lab_hours": int,
#       "marks": {"attendance": n, "class_test": n, "mid": n, "final": n},
#       "topics": [{"name", "yield": "high|medium|low", "status": "Pending|Studying|Completed"}]
#   }}}
#
# Semester dropdown filters the main table; row click opens a side-drawer with
# mark distribution, credit matrix and high/low-yield topic clusters; every
# status change is pushed through the broker so Home Cockpit updates instantly.

import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QComboBox, QSpinBox, QPushButton, QFrame, QTableWidget, QTableWidgetItem,
    QSplitter, QScrollArea, QFileDialog, QMessageBox, QDialog,
    QHeaderView,
)

COURSE_STATUSES = ["Pending", "Studying", "Revision", "Completed"]
PRIORITIES = ["HIGH", "MEDIUM", "LOW"]
TOPIC_YIELDS = ["high", "medium", "low"]
TOPIC_STATUSES = ["Pending", "Studying", "Completed"]
MARKS_LABELS = [("attendance", "Attendance"), ("class_test", "Class Test"),
                ("mid", "Mid"), ("final", "Final")]

TABLE_COLUMNS = ["Semester", "Code", "Priority", "Status", "Credits",
                 "Theory", "Lab", "Topics"]


# ---------------------------------------------------------------------------
# Broker helpers (also used by Home Cockpit for live grade inputs)
# ---------------------------------------------------------------------------
def semesters_map(broker):
    return broker.get("syllabus.semesters", {}) or {}


def all_courses(broker):
    """Yield (semester, code, course) rows across every semester."""
    for sem, courses in (semesters_map(broker)).items():
        for code, course in (courses or {}).items():
            yield sem, code, course


def live_unstudied_topics(broker):
    """Count of high-yield topics not yet Completed in the active semester
    (falling back to all semesters when none is active). Feeds the grade model."""
    sems = semesters_map(broker)
    active = broker.get("syllabus.active_semester")
    keys = [active] if (active and active in sems) else list(sems.keys())
    count = 0
    for sem in keys:
        for course in (sems.get(sem) or {}).values():
            for topic in (course.get("topics", []) or []):
                if not isinstance(topic, dict):
                    continue
                if str(topic.get("yield", "")).lower() == "high" and \
                        str(topic.get("status", "")).lower() != "completed":
                    count += 1
    return count


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------
class CourseDialog(QDialog):
    """Add / edit one course under the active semester."""

    def __init__(self, parent=None, course=None):
        super().__init__(parent)
        self.setWindowTitle("Course")
        self.setMinimumWidth(360)
        grid = QGridLayout(self)
        grid.setSpacing(6)

        self.code_edit = QLineEdit()
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(PRIORITIES)
        self.status_combo = QComboBox()
        self.status_combo.addItems(COURSE_STATUSES)
        self.credits_spin = QSpinBox()
        self.credits_spin.setRange(0, 10)
        self.theory_spin = QSpinBox()
        self.theory_spin.setRange(0, 20)
        self.lab_spin = QSpinBox()
        self.lab_spin.setRange(0, 20)
        self.marks_spins = {}
        for i, (key, label) in enumerate(MARKS_LABELS):
            spin = QSpinBox()
            spin.setRange(0, 100)
            self.marks_spins[key] = spin
            self.marks_spins[key].setValue(5 if key == "attendance" else
                                           15 if key == "class_test" else
                                           30 if key == "mid" else 50)

        rows = [("Course code", self.code_edit), ("Priority", self.priority_combo),
                ("Status", self.status_combo), ("Credits", self.credits_spin),
                ("Theory hours", self.theory_spin), ("Lab hours", self.lab_spin)]
        for row, (label, widget) in enumerate(rows):
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(widget, row, 1)

        marks_label = QLabel("Mark distribution")
        marks_label.setProperty("muted", True)
        grid.addWidget(marks_label, len(rows), 0, 1, 2)
        for i, (key, label) in enumerate(MARKS_LABELS):
            grid.addWidget(QLabel(label), len(rows) + 1 + i, 0)
            grid.addWidget(self.marks_spins[key], len(rows) + 1 + i, 1)

        buttons = _button_box(self)
        grid.addWidget(buttons, len(rows) + 1 + len(MARKS_LABELS), 0, 1, 2)

        if course:
            self.code_edit.setText(course.get("code", ""))
            self._set_combo(self.priority_combo, course.get("priority", "MEDIUM"))
            self._set_combo(self.status_combo, course.get("status", "Pending"))
            self.credits_spin.setValue(int(course.get("credits", 0)))
            self.theory_spin.setValue(int(course.get("theory_hours", 0)))
            self.lab_spin.setValue(int(course.get("lab_hours", 0)))
            marks = course.get("marks", {}) or {}
            for key in self.marks_spins:
                self.marks_spins[key].setValue(int(marks.get(key, 0)))

    @staticmethod
    def _set_combo(combo, value):
        index = combo.findText(str(value))
        combo.setCurrentIndex(index if index >= 0 else 0)

    def result_data(self):
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return {
            "code": self.code_edit.text().strip().upper(),
            "priority": self.priority_combo.currentText(),
            "status": self.status_combo.currentText(),
            "credits": self.credits_spin.value(),
            "theory_hours": self.theory_spin.value(),
            "lab_hours": self.lab_spin.value(),
            "marks": {key: spin.value() for key, spin in self.marks_spins.items()},
            "topics": [],
        }


class TopicDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Topic")
        form = QGridLayout(self)
        form.setSpacing(6)
        self.name_edit = QLineEdit()
        self.yield_combo = QComboBox()
        self.yield_combo.addItems(TOPIC_YIELDS)
        self.status_combo = QComboBox()
        self.status_combo.addItems(TOPIC_STATUSES)
        for row, (label, widget) in enumerate(
                [("Topic name", self.name_edit), ("Yield", self.yield_combo),
                 ("Status", self.status_combo)]):
            form.addWidget(QLabel(label), row, 0)
            form.addWidget(widget, row, 1)
        form.addWidget(_button_box(self), 3, 0, 1, 2)

    def result_data(self):
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        return {"name": self.name_edit.text().strip(),
                "yield": self.yield_combo.currentText(),
                "status": self.status_combo.currentText()}


def _button_box(parent):
    from PyQt6.QtWidgets import QDialogButtonBox
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                           QDialogButtonBox.StandardButton.Cancel)
    box.accepted.connect(parent.accept)
    box.rejected.connect(parent.reject)
    return box


# ---------------------------------------------------------------------------
# The tab
# ---------------------------------------------------------------------------
class SyllabusTab(QWidget):
    def __init__(self, broker, parent=None):
        super().__init__(parent)
        self.broker = broker
        self._selection = None  # (semester, code)
        self._semester_filter = None
        self._build_ui()
        self._reload()
        broker.section_changed.connect(self._on_section_changed)

    # -------------------------------------------------------------- UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        header = QLabel("Syllabus Engine · Subject Hub")
        header.setProperty("role", "active")
        header.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(header)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Semester"))
        self.semester_combo = QComboBox()
        self.semester_combo.currentIndexChanged.connect(self._on_semester_filter)
        toolbar.addWidget(self.semester_combo)
        toolbar.addStretch(1)

        import_btn = QPushButton("Import syllabus JSON")
        import_btn.clicked.connect(self._import_json)
        add_btn = QPushButton("Add course")
        add_btn.clicked.connect(self._add_course)
        for btn in (import_btn, add_btn):
            toolbar.addWidget(btn)
        root.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self.table = QTableWidget(0, len(TABLE_COLUMNS))
        self.table.setHorizontalHeaderLabels(TABLE_COLUMNS)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        self.table.horizontalHeader().setStretchLastSection(True)
        splitter.addWidget(self.table)

        splitter.addWidget(self._build_drawer())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.drawer_splitter = splitter
        root.addWidget(splitter, 1)

    def _build_drawer(self):
        self.drawer = QFrame()
        self.drawer.setProperty("panel", True)
        self.drawer.setMinimumWidth(300)

        outer = QVBoxLayout(self.drawer)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        self.drawer_title = QLabel("Select a course")
        self.drawer_title.setProperty("role", "active")
        self.drawer_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        outer.addWidget(self.drawer_title)

        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Status"))
        self.status_combo = QComboBox()
        self.status_combo.addItems(COURSE_STATUSES)
        self.status_combo.currentTextChanged.connect(self._on_status_change)
        status_row.addWidget(self.status_combo, 1)
        status_row.addWidget(QLabel("Priority"))
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(PRIORITIES)
        self.priority_combo.currentTextChanged.connect(self._on_priority_change)
        status_row.addWidget(self.priority_combo, 1)
        outer.addLayout(status_row)

        marks_title = QLabel("Mark distribution")
        marks_title.setProperty("muted", True)
        outer.addWidget(marks_title)
        self.marks_table = QTableWidget(len(MARKS_LABELS), 3)
        self.marks_table.setHorizontalHeaderLabels(["Component", "Marks", "Share"])
        self.marks_table.verticalHeader().setVisible(False)
        self.marks_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.marks_table.setMaximumHeight(6 + 28 * (len(MARKS_LABELS) + 1))
        self.marks_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        outer.addWidget(self.marks_table)

        credit_title = QLabel("Credit matrix")
        credit_title.setProperty("muted", True)
        outer.addWidget(credit_title)
        self.credit_line = QLabel("")
        self.credit_line.setProperty("mono", True)
        outer.addWidget(self.credit_line)

        clusters_title = QLabel("Topic clusters (by yield)")
        clusters_title.setProperty("muted", True)
        outer.addWidget(clusters_title)
        self.topics_box = QWidget()
        self.topics_layout = QVBoxLayout(self.topics_box)
        self.topics_layout.setContentsMargins(0, 0, 0, 0)
        self.topics_layout.setSpacing(4)
        self.topics_scroll = QScrollArea()
        self.topics_scroll.setWidgetResizable(True)
        self.topics_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.topics_scroll.setWidget(self.topics_box)
        outer.addWidget(self.topics_scroll, 1)

        add_topic = QPushButton("Add topic")
        add_topic.clicked.connect(self._add_topic)
        outer.addWidget(add_topic)

        actions = QHBoxLayout()
        edit_btn = QPushButton("Edit course")
        edit_btn.clicked.connect(self._edit_course)
        delete_btn = QPushButton("Delete course")
        delete_btn.clicked.connect(self._delete_course)
        actions.addWidget(edit_btn)
        actions.addWidget(delete_btn)
        outer.addLayout(actions)

        self.drawer.hide()
        return self.drawer

    # -------------------------------------------------------- reloading
    def _on_section_changed(self, section, _value):
        if section == "syllabus":
            self._reload()

    def _reload(self):
        sems = semesters_map(self.broker)
        active = self.broker.get("syllabus.active_semester")

        # semester dropdown
        self.semester_combo.blockSignals(True)
        self.semester_combo.clear()
        self.semester_combo.addItem("All semesters", None)
        for sem in sems:
            self.semester_combo.addItem(sem, sem)
        index = self.semester_combo.findData(active)
        self.semester_combo.setCurrentIndex(index if index >= 0 else 0)
        self._semester_filter = active
        self.semester_combo.blockSignals(False)

        # table
        rows = []
        for sem, code, course in all_courses(self.broker):
            if self._semester_filter and sem != self._semester_filter:
                continue
            topics = course.get("topics", []) or []
            rows.append((sem, code, course, topics))
        rows.sort(key=lambda r: (r[0], r[1]))

        self.table.setRowCount(0)
        for sem, code, course, topics in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [sem, code,
                      course.get("priority", "—"), course.get("status", "—"),
                      str(course.get("credits", 0)),
                      str(course.get("theory_hours", 0)),
                      str(course.get("lab_hours", 0)), str(len(topics))]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, (sem, code))
                if col in (4, 5, 6, 7):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, item)

        # restore selection if still present
        if self._selection and self._selection in {
            (sem, code) for sem, code, _, _ in rows}:
            for row in range(self.table.rowCount()):
                if self.table.item(row, 1).data(Qt.ItemDataRole.UserRole) == \
                        self._selection:
                    self.table.selectRow(row)
                    break
        else:
            self._selection = None
            self._show_drawer(None)

        # "no data" hint
        if not rows:
            self.drawer_title.setText("No courses — import syllabus JSON or add one")
            if not self.drawer.isHidden():
                self.drawer.show()

    def _on_semester_filter(self, _index):
        value = self.semester_combo.currentData()
        self._semester_filter = value
        self.broker.set("syllabus.active_semester", value)
        self._reload()

    # ------------------------------------------------------ selection
    def _on_row_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._show_drawer(None)
            return
        item = self.table.item(rows[0].row(), 1)
        if item is None:
            self._show_drawer(None)
            return
        self._selection = item.data(Qt.ItemDataRole.UserRole)
        self._show_drawer(self._selection)

    def _selected_course(self):
        if not self._selection:
            return None, None
        sem, code = self._selection
        return (sem, code), (semesters_map(self.broker).get(sem) or {}).get(code)

    def _show_drawer(self, selection):
        if not selection:
            self.drawer.hide()
            return
        sem, code = selection
        course = (semesters_map(self.broker).get(sem) or {}).get(code)
        if not course:
            self.drawer.hide()
            return
        self.drawer.show()

        self.drawer_title.setText(f"{code}  ·  {sem}")
        self.status_combo.blockSignals(True)
        self._set_combo_value(self.status_combo, course.get("status", "Pending"))
        self.status_combo.blockSignals(False)
        self.priority_combo.blockSignals(True)
        self._set_combo_value(self.priority_combo, course.get("priority", "MEDIUM"))
        self.priority_combo.blockSignals(False)

        self._fill_marks(course)
        self._fill_credit_matrix(sem, course)
        self._fill_topics(sem, code, course.get("topics", []) or [])

    @staticmethod
    def _set_combo_value(combo, value):
        index = combo.findText(str(value))
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.addItem(str(value))
            combo.setCurrentIndex(combo.count() - 1)

    def _fill_marks(self, course):
        marks = course.get("marks", {}) or {}
        values = [(label, int(marks.get(key, 0))) for key, label in MARKS_LABELS]
        total = sum(v for _, v in values)
        for row, (label, value) in enumerate(values):
            self.marks_table.setItem(row, 0, QTableWidgetItem(label))
            marks_item = QTableWidgetItem(str(value))
            marks_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.marks_table.setItem(row, 1, marks_item)
            share_item = QTableWidgetItem(
                f"{100.0 * value / total:.0f}%" if total else "—")
            share_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.marks_table.setItem(row, 2, share_item)

    def _fill_credit_matrix(self, sem, course):
        credits = int(course.get("credits", 0))
        theory = int(course.get("theory_hours", 0))
        lab = int(course.get("lab_hours", 0))
        total_c = total_t = total_l = 0
        for _sem, _code, c in all_courses(self.broker):
            if _sem == sem:
                total_c += int(c.get("credits", 0))
                total_t += int(c.get("theory_hours", 0))
                total_l += int(c.get("lab_hours", 0))
        self.credit_line.setText(
            f"course: {credits} cr · {theory} theory · {lab} lab h\n"
            f"semester total ({sem}): {total_c} cr · {total_t} theory · {total_l} lab h")

    def _fill_topics(self, sem, code, topics):
        # clear previous topic rows
        while self.topics_layout.count():
            item = self.topics_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not topics:
            hint = QLabel("No topics yet")
            hint.setProperty("muted", True)
            self.topics_layout.addWidget(hint)

        for yield_name in TOPIC_YIELDS:
            bucket = [i for i, t in enumerate(topics)
                      if isinstance(t, dict) and
                      str(t.get("yield", "")).lower() == yield_name]
            if not bucket:
                continue
            header = QLabel(f"· {yield_name.upper()} yield ({len(bucket)})")
            header.setProperty("role", "predictive" if yield_name == "high" else "muted")
            header.setStyleSheet("font-weight: 600; margin-top: 4px;")
            self.topics_layout.addWidget(header)
            for i in bucket:
                topic = topics[i]
                row_widget = QWidget()
                row = QHBoxLayout(row_widget)
                row.setContentsMargins(0, 0, 0, 0)
                name = QLabel(topic.get("name", "—"))
                name.setWordWrap(True)
                row.addWidget(name, 1)
                status_combo = QComboBox()
                status_combo.addItems(TOPIC_STATUSES)
                self._set_combo_value(status_combo, topic.get("status", "Pending"))
                status_combo.currentTextChanged.connect(
                    lambda text, s=sem, c=code, i=i: self._set_topic_status(
                        s, c, i, text))
                row.addWidget(status_combo)
                delete = QPushButton("×")
                delete.setFixedWidth(24)
                delete.clicked.connect(
                    lambda _=False, s=sem, c=code, i=i: self._delete_topic(s, c, i))
                row.addWidget(delete)
                self.topics_layout.addWidget(row_widget)

    # --------------------------------------------------------- mutations
    def _set_topic_status(self, sem, code, index, status):
        key = f"syllabus.semesters.{sem}.{code}.topics.{index}.status"
        self.broker.set(key, status)

    def _delete_topic(self, sem, code, index):
        course = (semesters_map(self.broker).get(sem) or {}).get(code)
        if not course:
            return
        topics = list(course.get("topics", []) or [])
        if 0 <= index < len(topics):
            del topics[index]
            self.broker.set(f"syllabus.semesters.{sem}.{code}.topics", topics)

    def _on_status_change(self, status):
        if self._selection:
            self.broker.set(
                f"syllabus.semesters.{self._selection[0]}.{self._selection[1]}.status",
                status)

    def _on_priority_change(self, priority):
        if self._selection:
            self.broker.set(
                f"syllabus.semesters.{self._selection[0]}.{self._selection[1]}.priority",
                priority)

    def _add_topic(self):
        sem, code = self._selection or (None, None)
        if not sem:
            return
        data = TopicDialog(self).result_data()
        if not data or not data.get("name"):
            return
        course = (semesters_map(self.broker).get(sem) or {}).get(code)
        if not course:
            return
        topics = list(course.get("topics", []) or [])
        topics.append(data)
        self.broker.set(f"syllabus.semesters.{sem}.{code}.topics", topics)

    def _active_semester(self):
        active = self.broker.get("syllabus.active_semester")
        if not active:
            QMessageBox.information(
                self, "Semester required",
                "Pick a semester in the dropdown first, then add a course.")
            return None
        return active

    def _add_course(self):
        sem = self._active_semester()
        if not sem:
            return
        data = CourseDialog(self).result_data()
        if not data or not data.get("code"):
            return
        sems = semesters_map(self.broker)
        courses = dict(sems.get(sem) or {})
        courses[data["code"]] = data
        sems[sem] = courses
        self.broker.set("syllabus.semesters", sems)

    def _edit_course(self):
        selection, course = self._selected_course()
        if not selection or not course:
            return
        sem, code = selection
        data = CourseDialog(self, dict(course, code=code)).result_data()
        if not data or not data.get("code"):
            return
        sems = semesters_map(self.broker)
        courses = dict(sems.get(sem) or {})
        old = courses.pop(code, course)
        data["topics"] = old.get("topics", []) or []
        courses[data["code"]] = data
        sems[sem] = courses
        self.broker.set("syllabus.semesters", sems)
        self._selection = (sem, data["code"])

    def _delete_course(self):
        selection, course = self._selected_course()
        if not selection or not course:
            return
        sem, code = selection
        if QMessageBox.question(
                self, "Delete course",
                f"Delete {code} from {sem}?") != QMessageBox.StandardButton.Yes:
            return
        sems = semesters_map(self.broker)
        courses = dict(sems.get(sem) or {})
        courses.pop(code, None)
        sems[sem] = courses
        self.broker.set("syllabus.semesters", sems)
        self._selection = None

    def _import_json(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import syllabus JSON", "",
            "Syllabus files (*.json);;All files (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "Import failed", f"Cannot read file:\n{exc}")
            return
        if not isinstance(data, dict):
            QMessageBox.warning(self, "Import failed", "Root must be a JSON object.")
            return

        sems = semesters_map(self.broker)
        merged = 0
        for sem, courses in data.items():
            if not isinstance(courses, dict):
                continue
            merged_courses = dict(sems.get(sem) or {})
            for code, course in courses.items():
                if isinstance(course, dict):
                    merged_courses[code] = course
                    merged += 1
            sems[sem] = merged_courses
        self.broker.set("syllabus.semesters", sems)
        QMessageBox.information(
            self, "Import complete", f"Imported {merged} course(s).")
