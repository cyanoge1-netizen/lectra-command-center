# File Location: profiles_tab.py
# Academic & Life Command Center — Profiles tab (Phase 4).
#
# Left:   editable student card (photo + every profile.student field incl.
#         CGPA). Saves through the broker, so Home Cockpit's CGPA KPI and any
#         other tab update live.
# Right:  instructor grid: list pane (left) -> detail panel (right) on click,
#         with add / edit / delete. Stored in broker profile.instructors.

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QDoubleSpinBox, QPushButton, QFrame, QListWidget, QListWidgetItem,
    QDialog, QFileDialog, QSplitter, QScrollArea, QDialogButtonBox,
)

# (broker key, form label) — mirrors the schema under profile.student
STUDENT_FIELDS = [
    ("full_name", "Full Name"),
    ("roll_no", "Roll No"),
    ("reg_no", "Reg No"),
    ("institute", "Institute"),
    ("department", "Department"),
    ("course", "Course"),
    ("semester", "Semester"),
    ("session", "Session"),
    ("email", "Email"),
    ("phone", "Phone"),
    ("blood_group", "Blood Group"),
    ("address", "Address"),
]

PHOTO_SIZE = 128


def _scaled_pixmap(path, size=PHOTO_SIZE):
    """Load + scale a photo for display, or None when unreadable."""
    if not path:
        return None
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return None
    return pixmap.scaled(size, size,
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)


def _photo_label(panel, title):
    """A placeholder + change-photo button cluster shared by student/instructor."""
    box = QFrame()
    box.setProperty("panel", True)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(6)

    photo = QLabel()
    photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    photo.setFixedHeight(PHOTO_SIZE + 8)
    photo.setFixedWidth(PHOTO_SIZE + 8)
    photo.setText("no photo")
    photo.setProperty("muted", True)
    layout.addWidget(photo)

    pick = QPushButton(title)
    layout.addWidget(pick)
    return box, photo, pick


class InstructorDialog(QDialog):
    """Add / edit dialog for one instructor entry."""

    def __init__(self, parent=None, instructor=None):
        super().__init__(parent)
        self.setWindowTitle("Instructor")
        self.setMinimumWidth(380)

        form = QFormLayout(self)
        self.name_edit = QLineEdit()
        self.contact_edit = QLineEdit()
        self.office_edit = QLineEdit()
        self.courses_edit = QLineEdit()
        self.photo_path = ""

        form.addRow("Name", self.name_edit)
        form.addRow("Contact (email/phone)", self.contact_edit)
        form.addRow("Office room", self.office_edit)
        form.addRow("Active courses (comma-separated)", self.courses_edit)

        photo_row = QHBoxLayout()
        self.photo_field = QLineEdit()
        self.photo_field.setReadOnly(True)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_photo)
        photo_row.addWidget(self.photo_field, 1)
        photo_row.addWidget(browse)
        form.addRow("Photo", photo_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        if instructor:
            self.name_edit.setText(instructor.get("name", ""))
            self.contact_edit.setText(instructor.get("contact", ""))
            self.office_edit.setText(instructor.get("office_room", ""))
            self.courses_edit.setText(", ".join(instructor.get("active_courses", [])))
            self._set_photo(instructor.get("photo_path", ""))

    def _browse_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose photo", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self._set_photo(path)

    def _set_photo(self, path):
        self.photo_path = path
        self.photo_field.setText(path)

    def result_data(self):
        """The filled instructor dict, or None if the user cancelled."""
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        courses = [c.strip() for c in self.courses_edit.text().split(",") if c.strip()]
        return {
            "name": self.name_edit.text().strip(),
            "contact": self.contact_edit.text().strip(),
            "office_room": self.office_edit.text().strip(),
            "active_courses": courses,
            "photo_path": self.photo_path,
        }


class ProfilesTab(QWidget):
    """Student card + instructor grid, both persisted through the broker."""

    def __init__(self, broker, parent=None):
        super().__init__(parent)
        self.broker = broker
        self._student_edits = {}
        self._build_ui()
        self._reload_from_broker()
        broker.section_changed.connect(self._on_section_changed)

    # -------------------------------------------------------------- UI
    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        splitter.addWidget(self._build_student_card())
        splitter.addWidget(self._build_instructor_section())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def _build_student_card(self):
        card = QFrame()
        card.setProperty("panel", True)

        root = QVBoxLayout(card)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        title = QLabel("Student Profile")
        title.setProperty("role", "active")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        self.onboarding = QLabel(
            "Fill in your details below and save. Your name, institute and "
            "CGPA show up in the Home Cockpit, and a photo is included in "
            "your backups. Start with your Full Name and Course, then add "
            "your instructors on the right.")
        self.onboarding.setProperty("panel", True)
        self.onboarding.setProperty("muted", True)
        self.onboarding.setWordWrap(True)
        self.onboarding.setVisible(False)
        root.addWidget(self.onboarding)

        top = QHBoxLayout()
        self.student_photo_box, self.student_photo, pick = \
            _photo_label(card, "Change photo")
        pick.clicked.connect(self._pick_student_photo)
        top.addWidget(self.student_photo_box)

        self.cgpa_spin = QDoubleSpinBox()
        self.cgpa_spin.setRange(0.0, 4.0)
        self.cgpa_spin.setDecimals(2)
        self.cgpa_spin.setSingleStep(0.05)
        top.addLayout(self._wrap_row("CGPA", self.cgpa_spin), 1)

        root.addLayout(top)

        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for key, label in STUDENT_FIELDS:
            edit = QLineEdit()
            edit.setProperty("mono", key in ("roll_no", "reg_no", "email", "phone"))
            self._student_edits[key] = edit
            self.form.addRow(label, edit)
        root.addLayout(self.form)

        save = QPushButton("Save student profile")
        save.clicked.connect(self._save_student)
        root.addWidget(save)
        root.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(card)
        return scroll

    def _wrap_row(self, caption, widget):
        """A compact (caption, control) layout pair for the CGPA area."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QLabel(caption)
        label.setProperty("muted", True)
        layout.addWidget(label)
        layout.addWidget(widget)
        layout.addStretch(1)
        return layout

    def _build_instructor_section(self):
        section = QFrame()
        section.setProperty("panel", True)
        root = QVBoxLayout(section)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        title = QLabel("Instructors")
        title.setProperty("role", "active")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        inner = QSplitter(Qt.Orientation.Horizontal)
        inner.setChildrenCollapsible(False)

        # list pane
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.instructor_list = QListWidget()
        self.instructor_list.currentRowChanged.connect(self._show_instructor)
        left_layout.addWidget(self.instructor_list, 1)

        buttons = QHBoxLayout()
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_instructor)
        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(self._edit_instructor)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._delete_instructor)
        for btn in (add_btn, edit_btn, del_btn):
            buttons.addWidget(btn)
        left_layout.addLayout(buttons)

        # detail pane
        self.detail_photo_box, self.detail_photo, _ = \
            _photo_label(section, "")  # read-only photo placeholder
        self.detail_photo_box.setProperty("panel", False)
        self.detail_photo_box.setFixedWidth(PHOTO_SIZE + 24)
        self.detail_name = QLabel("—")
        self.detail_name.setStyleSheet("font-size: 15px; font-weight: 700;")
        self.detail_contact = QLabel("")
        self.detail_office = QLabel("")
        self.detail_courses = QLabel("")
        self.detail_courses.setWordWrap(True)
        for label in (self.detail_contact, self.detail_office, self.detail_courses):
            label.setProperty("mono", True)

        right = QFrame()
        right.setProperty("panel", True)
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.addWidget(self.detail_photo_box)
        details = QVBoxLayout()
        details.setSpacing(6)
        for label in (self.detail_name, self.detail_contact,
                      self.detail_office, self.detail_courses):
            details.addWidget(label)
        details.addStretch(1)
        right_layout.addLayout(details, 1)

        inner.addWidget(left)
        inner.addWidget(right)
        inner.setStretchFactor(0, 2)
        inner.setStretchFactor(1, 3)
        root.addWidget(inner, 1)
        return section

    # ------------------------------------------------ broker round-trips
    def _on_section_changed(self, section, _value):
        if section == "profile":
            self._reload_from_broker()

    def _reload_from_broker(self):
        student = self.broker.get("profile.student", {}) or {}
        for key, edit in self._student_edits.items():
            edit.setText(str(student.get(key, "") or ""))
        self.cgpa_spin.setValue(float(student.get("cgpa") or 0.0))
        self._load_student_photo(student.get("photo_path", ""))

        # Empty-state onboarding hint: visible until the profile has content.
        empty = (not str(student.get("full_name", "") or "").strip()
                 and not float(student.get("cgpa") or 0.0))
        self.onboarding.setVisible(empty)

        instructors = self.broker.get("profile.instructors", []) or []
        self.instructor_list.blockSignals(True)
        self.instructor_list.clear()
        for instructor in instructors:
            self.instructor_list.addItem(
                QListWidgetItem(instructor.get("name", "—")))
        self.instructor_list.blockSignals(False)
        self._show_instructor(self.instructor_list.currentRow())

    def _load_student_photo(self, path):
        pixmap = _scaled_pixmap(path)
        if pixmap is None:
            self.student_photo.setText("no photo")
            self.student_photo.setPixmap(QPixmap())
        else:
            self.student_photo.setPixmap(pixmap)

    def _pick_student_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose student photo", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self.broker.set("profile.student.photo_path", path)
            self._load_student_photo(path)

    def _save_student(self):
        updates = {
            "profile.student." + key: edit.text().strip()
            for key, edit in self._student_edits.items()
        }
        updates["profile.student.cgpa"] = round(self.cgpa_spin.value(), 2)
        self.broker.set_many(updates)

    # ------------------------------------------------- instructors
    def _instructors(self):
        return list(self.broker.get("profile.instructors", []) or [])

    def _save_instructors(self, instructors):
        self.broker.set("profile.instructors", instructors)

    def _current_index(self):
        return self.instructor_list.currentRow()

    def _add_instructor(self):
        data = InstructorDialog(self).result_data()
        if not data or not data.get("name"):
            return
        instructors = self._instructors()
        instructors.append(data)
        self._save_instructors(instructors)
        self.instructor_list.setCurrentRow(len(instructors) - 1)

    def _edit_instructor(self):
        index = self._current_index()
        if index < 0:
            return
        instructors = self._instructors()
        data = InstructorDialog(self, instructors[index]).result_data()
        if not data:
            return
        instructors[index] = data
        self._save_instructors(instructors)
        self.instructor_list.setCurrentRow(index)

    def _delete_instructor(self):
        index = self._current_index()
        if index < 0:
            return
        instructors = self._instructors()
        del instructors[index]
        self._save_instructors(instructors)

    def _show_instructor(self, index):
        instructors = self._instructors()
        if index is None or index < 0 or index >= len(instructors):
            self.detail_name.setText("—")
            self.detail_contact.setText("")
            self.detail_office.setText("")
            self.detail_courses.setText("")
            self.detail_photo.setPixmap(QPixmap())
            self.detail_photo.setText("no photo")
            return

        instructor = instructors[index]
        self.detail_name.setText(instructor.get("name", "—"))
        self.detail_contact.setText(f"Contact: {instructor.get('contact', '—')}")
        self.detail_office.setText(f"Office: {instructor.get('office_room', '—')}")
        courses = instructor.get("active_courses", []) or []
        self.detail_courses.setText(
            "Active courses: " + (", ".join(courses) if courses else "—"))

        pixmap = _scaled_pixmap(instructor.get("photo_path", ""))
        if pixmap is None:
            self.detail_photo.setText("no photo")
            self.detail_photo.setPixmap(QPixmap())
        else:
            self.detail_photo.setPixmap(pixmap)
