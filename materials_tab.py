# -*- coding: utf-8 -*-
"""Materials tab (Phase 8 — final).

EdX/Video dashboard. Left: hierarchical course directory (course -> classes
with notes/slides attachments). Center/right: media canvas backed by the
yt-dlp wrapper (probe metadata + thumbnail, native playback, download) plus a
completion progress tracker and an inline notepad per class.

Persisted in the broker section `materials`:
  courses    : { CODE: { title, classes: { class_title:
                  { video_url, notes_path, slides_path, notepad } } } }
  completion : { CODE: [ completed class titles ] }
"""
import os
import subprocess
import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QDialog, QFormLayout,
    QLineEdit, QFileDialog, QMessageBox, QCheckBox, QPlainTextEdit,
    QFrame, QProgressBar,
)

import media_backend
from styles import COLORS

MEDIA_DIR = os.path.join(os.getcwd(), "media")
THUMB_DIR = os.path.join(MEDIA_DIR, "thumbs")
DL_DIR = os.path.join(MEDIA_DIR, "downloads")


def _fmt_duration(seconds):
    if not seconds:
        return ""
    seconds = int(seconds)
    h, m = divmod(seconds, 3600)
    m, s = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class CourseDialog(QDialog):
    def __init__(self, parent=None, code="", title=""):
        super().__init__(parent)
        self.setWindowTitle("Add course")
        self.setMinimumWidth(340)
        form = QFormLayout(self)
        self.code = QLineEdit(code)
        self.code.setPlaceholderText("e.g. CSE101")
        self.title = QLineEdit(title)
        form.addRow("Code", self.code)
        form.addRow("Title", self.title)
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
        return self.code.text().strip(), self.title.text().strip()


class ClassDialog(QDialog):
    def __init__(self, parent=None, cls=None):
        super().__init__(parent)
        self.setWindowTitle("Edit class" if cls else "Add class")
        self.setMinimumWidth(420)
        cls = cls or {}
        form = QFormLayout(self)
        self.title = QLineEdit(cls.get("title", ""))
        self.title.setPlaceholderText("e.g. Lecture 1 — Intro to DB")
        self.video = QLineEdit(cls.get("video_url", ""))
        self.video.setPlaceholderText("https://… (YouTube / any yt-dlp site)")
        self.notes = QLineEdit(cls.get("notes_path", ""))
        self.slides = QLineEdit(cls.get("slides_path", ""))
        form.addRow("Title", self.title)
        form.addRow("Video URL", self.video)
        form.addRow("Notes file", self._with_browse(self.notes))
        form.addRow("Slides file", self._with_browse(self.slides))
        ok = QPushButton("Save")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        form.addRow(row)

    def _with_browse(self, line_edit):
        box = QHBoxLayout()
        box.addWidget(line_edit)
        button = QPushButton("…")
        button.setFixedWidth(34)

        def browse():
            path, _ = QFileDialog.getOpenFileName(
                self, "Choose file", "",
                "Documents (*.pdf *.ppt *.pptx *.doc *.docx *.md *.txt)")
            if path:
                line_edit.setText(path)

        button.clicked.connect(browse)
        box.addWidget(button)
        holder = QWidget()
        holder.setLayout(box)
        return holder

    def values(self):
        return {
            "title": self.title.text().strip(),
            "video_url": self.video.text().strip(),
            "notes_path": self.notes.text().strip(),
            "slides_path": self.slides.text().strip(),
        }


class MaterialsTab(QWidget):
    _result = pyqtSignal(str, object)

    def __init__(self, broker):
        super().__init__()
        self.broker = broker
        self._updating = False
        self._selected = (None, None)  # survives rebuilds
        self._current = (None, None)  # what the detail panel shows

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(self._build_directory(), 1)
        row.addWidget(self._build_detail(), 2)
        outer.addLayout(row, 1)

        self._result.connect(self._on_result)
        self.broker.section_changed.connect(self._on_section_changed)
        self._rebuild()

    # ------------------------------------------------------------- panels
    def _build_directory(self):
        panel = QFrame()
        panel.setProperty("panel", True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title = QLabel("Course directory")
        title.setProperty("role", "active")
        layout.addWidget(title)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFormat("%v/%m classes")
        layout.addWidget(self.progress_bar)
        self.summary_lbl = QLabel("")
        self.summary_lbl.setProperty("muted", True)
        layout.addWidget(self.summary_lbl)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Class", "State"])
        self.tree.setColumnWidth(0, 200)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree, 1)

        grid = QGridLayout()
        add_course = QPushButton("+ Course")
        add_course.clicked.connect(self._add_course)
        add_class = QPushButton("+ Class")
        add_class.clicked.connect(self._add_class)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_selected)
        grid.addWidget(add_course, 0, 0)
        grid.addWidget(add_class, 0, 1)
        grid.addWidget(remove, 0, 2)
        layout.addLayout(grid)

        self.tree.currentItemChanged.connect(self._on_tree_select)
        return panel

    def _build_detail(self):
        panel = QFrame()
        panel.setProperty("panel", True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.class_title_lbl = QLabel("Select a class")
        self.class_title_lbl.setProperty("role", "active")
        header.addWidget(self.class_title_lbl, 1)
        self.state_lbl = QLabel("")
        self.state_lbl.setProperty("mono", True)
        header.addWidget(self.state_lbl)
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.clicked.connect(self._edit_current)
        self.edit_btn.setEnabled(False)
        header.addWidget(self.edit_btn)
        layout.addLayout(header)

        # media canvas
        canvas = QFrame()
        canvas.setProperty("panel", True)
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(8, 8, 8, 8)
        canvas_layout.setSpacing(4)
        self.thumb_lbl = QLabel("No video selected")
        self.thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_lbl.setMinimumHeight(150)
        self.thumb_lbl.setStyleSheet(
            f"background: {COLORS['bg_base']}; color: {COLORS['text_muted']};"
            "border-radius: 4px;")
        canvas_layout.addWidget(self.thumb_lbl)
        self.meta_lbl = QLabel("")
        self.meta_lbl.setProperty("mono", True)
        self.meta_lbl.setWordWrap(True)
        canvas_layout.addWidget(self.meta_lbl)
        self.url_lbl = QLabel("")
        self.url_lbl.setProperty("muted", True)
        self.url_lbl.setWordWrap(True)
        canvas_layout.addWidget(self.url_lbl)
        media_row = QHBoxLayout()
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(lambda: self._play_video())
        self.download_btn = QPushButton("Download")
        self.download_btn.clicked.connect(self._download_video)
        self.browser_btn = QPushButton("Open in browser")
        self.browser_btn.clicked.connect(lambda: self._open_video())
        for b in (self.play_btn, self.download_btn, self.browser_btn):
            b.setEnabled(False)
            media_row.addWidget(b)
        media_row.addStretch(1)
        canvas_layout.addLayout(media_row)
        self.backend_lbl = QLabel("")
        self.backend_lbl.setProperty("mono", True)
        self.backend_lbl.setWordWrap(True)
        canvas_layout.addWidget(self.backend_lbl)
        layout.addWidget(canvas)

        # attachments
        attach = QGridLayout()
        attach.addWidget(QLabel("Notes:"), 0, 0)
        self.notes_lbl = QLabel("—")
        self.notes_lbl.setProperty("mono", True)
        attach.addWidget(self.notes_lbl, 0, 1)
        notes_btn = QPushButton("…")
        notes_btn.setFixedWidth(34)
        notes_btn.clicked.connect(lambda: self._browse_attachment("notes"))
        attach.addWidget(notes_btn, 0, 2)
        notes_open = QPushButton("Open")
        notes_open.setFixedWidth(56)
        notes_open.clicked.connect(lambda: self._open_attachment("notes"))
        attach.addWidget(notes_open, 0, 3)
        attach.addWidget(QLabel("Slides:"), 1, 0)
        self.slides_lbl = QLabel("—")
        self.slides_lbl.setProperty("mono", True)
        attach.addWidget(self.slides_lbl, 1, 1)
        slides_btn = QPushButton("…")
        slides_btn.setFixedWidth(34)
        slides_btn.clicked.connect(lambda: self._browse_attachment("slides"))
        attach.addWidget(slides_btn, 1, 2)
        slides_open = QPushButton("Open")
        slides_open.setFixedWidth(56)
        slides_open.clicked.connect(lambda: self._open_attachment("slides"))
        attach.addWidget(slides_open, 1, 3)
        layout.addLayout(attach)

        self.complete_cb = QCheckBox("Mark class as completed")
        self.complete_cb.stateChanged.connect(self._on_completion_toggled)
        layout.addWidget(self.complete_cb)

        notepad_title = QLabel("Inline notepad")
        notepad_title.setProperty("role", "active")
        layout.addWidget(notepad_title)
        self.notepad = QPlainTextEdit()
        self.notepad.setPlaceholderText("Lecture notes, doubts, action items…")
        layout.addWidget(self.notepad, 1)
        note_row = QHBoxLayout()
        self.note_hint = QLabel("")
        self.note_hint.setProperty("muted", True)
        note_row.addWidget(self.note_hint, 1)
        save_note = QPushButton("Save notepad")
        save_note.clicked.connect(self._save_notepad)
        note_row.addWidget(save_note)
        layout.addLayout(note_row)
        return panel

    # --------------------------------------------------- broker signals
    def _on_section_changed(self, section, _value):
        if section == "materials":
            self._rebuild()

    # ------------------------------------------------------------- data
    def _courses(self):
        return dict(self.broker.get("materials.courses", {}) or {})

    def _completion(self):
        return dict(self.broker.get("materials.completion", {}) or {})

    def _save_courses(self, courses):
        self.broker.set("materials.courses", courses)

    # ------------------------------------------------------------- rebuild
    def _rebuild(self):
        self._updating = True
        try:
            courses = self._courses()
            completion = self._completion()
            self.tree.clear()
            total = done = 0
            for code in sorted(courses):
                course = courses[code] or {}
                classes = course.get("classes", {}) or {}
                completed = set(completion.get(code, []) or [])
                course_item = QTreeWidgetItem(
                    [f"{code} — {course.get('title', '')}", ""])
                course_item.setData(0, Qt.ItemDataRole.UserRole, code)
                course_item.setData(0, Qt.ItemDataRole.UserRole + 1, None)
                self.tree.addTopLevelItem(course_item)
                for title in classes:
                    is_done = title in completed
                    item = QTreeWidgetItem(
                        [title, "done" if is_done else "pending"])
                    item.setData(0, Qt.ItemDataRole.UserRole, code)
                    item.setData(0, Qt.ItemDataRole.UserRole + 1, title)
                    course_item.addChild(item)
                    total += 1
                    done += 1 if is_done else 0
            self.progress_bar.setMaximum(max(1, total))
            self.progress_bar.setValue(done)
            self.summary_lbl.setText(
                f"{done}/{total} classes complete across "
                f"{len(courses)} course(s)")
            self._restore_selection()
            self._load_detail()
        finally:
            self._updating = False

    def _restore_selection(self):
        code, class_title = self._selected
        if code is None or code not in self._courses():
            self._selected = (None, None)
            return
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) != code:
                continue
            item.setExpanded(True)
            if not class_title:
                self.tree.setCurrentItem(item)
                return
            for j in range(item.childCount()):
                child = item.child(j)
                if child.data(0, Qt.ItemDataRole.UserRole + 1) == class_title:
                    self.tree.setCurrentItem(child)
                    return
            break

    def _on_tree_select(self, current, _previous):
        if current is None or self._updating:
            return
        self._selected = self._current_target()
        self._load_detail()

    def _current_target(self):
        item = self.tree.currentItem()
        if item is None:
            return None, None
        return (item.data(0, Qt.ItemDataRole.UserRole),
                item.data(0, Qt.ItemDataRole.UserRole + 1))

    def _load_detail(self):
        code, class_title = self._selected
        self._current = (code, class_title)
        self.thumb_lbl.setPixmap(QPixmap())
        self.thumb_lbl.setText("No video selected")
        self.meta_lbl.setText("")
        self.url_lbl.setText("")
        self.backend_lbl.setText("")
        self.notes_lbl.setText("—")
        self.slides_lbl.setText("—")
        self.notepad.setPlainText("")
        self.note_hint.setText("")
        self.edit_btn.setEnabled(False)
        for b in (self.play_btn, self.download_btn, self.browser_btn):
            b.setEnabled(False)
        self.complete_cb.blockSignals(True)
        self.complete_cb.setChecked(False)
        self.complete_cb.blockSignals(False)

        if not code or not class_title:
            self.class_title_lbl.setText("Select a class")
            self.state_lbl.setText("")
            return

        courses = self._courses()
        course = courses.get(code, {}) or {}
        cls = (course.get("classes", {}) or {}).get(class_title, {}) or {}
        completion = self._completion()
        is_done = class_title in set(completion.get(code, []) or [])
        self.class_title_lbl.setText(f"{class_title} · {code}")
        self.state_lbl.setText("done" if is_done else "pending")
        self.state_lbl.setProperty("mono", True)
        self.state_lbl.setStyleSheet(
            f"color: {COLORS['accent']};" if is_done
            else f"color: {COLORS['text_muted']};")
        self.edit_btn.setEnabled(True)
        self.complete_cb.blockSignals(True)
        self.complete_cb.setChecked(is_done)
        self.complete_cb.blockSignals(False)
        self.notepad.setPlainText(cls.get("notepad", ""))
        self.notes_lbl.setText(cls.get("notes_path") or "—")
        self.slides_lbl.setText(cls.get("slides_path") or "—")

        url = cls.get("video_url", "")
        if url:
            self.url_lbl.setText(url)
            for b in (self.play_btn, self.download_btn, self.browser_btn):
                b.setEnabled(True)
            self.thumb_lbl.setText("Loading media info…")
            self.backend_lbl.setText("")
            self._run_async("probe", lambda u=url: self._probe_and_thumb(u))
        else:
            self.thumb_lbl.setText("No video URL set — Edit class to add one")

    # ----------------------------------------------------- media canvas
    def _probe_and_thumb(self, url):
        meta = media_backend.probe(url) or {}
        thumb = media_backend.fetch_thumbnail(
            meta.get("thumbnail_url"), THUMB_DIR) if not meta.get("error") else None
        return {"meta": meta, "thumb": thumb}

    def _on_result(self, tag, payload):
        if tag == "probe":
            self._apply_probe(payload)
        elif tag == "play":
            self._apply_play(payload)
        elif tag == "download":
            self._apply_download(payload)

    def _apply_probe(self, payload):
        if self._current[1] is None:
            return
        thumb = payload.get("thumb")
        if thumb:
            pixmap = QPixmap(thumb)
            if not pixmap.isNull():
                self.thumb_lbl.setPixmap(pixmap.scaledToWidth(
                    self.thumb_lbl.width(), Qt.TransformationMode.SmoothTransformation))
                self.thumb_lbl.setText("")
        meta = payload.get("meta", {}) or {}
        if meta.get("error"):
            self.thumb_lbl.setText("Could not load media info")
            self.backend_lbl.setText(f"probe error: {meta['error']}")
            return
        if self.thumb_lbl.pixmap() is None or self.thumb_lbl.pixmap().isNull():
            self.thumb_lbl.setText("Preview unavailable")
        parts = [meta.get("title") or "Untitled media"]
        dur = _fmt_duration(meta.get("duration_seconds"))
        if dur:
            parts.append(dur)
        if meta.get("uploader"):
            parts.append(meta.get("uploader"))
        self.meta_lbl.setText("  ·  ".join(parts))
        self.backend_lbl.setText(f"yt-dlp: {media_backend.available()[1]}")

    def _play_video(self):
        url = self.url_lbl.text().strip()
        if not url:
            return
        self.backend_lbl.setText("Resolving stream…")
        self._run_async("play", lambda: media_backend.play(url))

    def _apply_play(self, payload):
        if payload.get("error"):
            self.backend_lbl.setText(f"playback failed: {payload['error']}")
        else:
            self.backend_lbl.setText(
                f"launched {payload.get('player')} for {payload.get('stream', '')[:60]}")

    def _download_video(self):
        url = self.url_lbl.text().strip()
        if not url:
            return
        self.backend_lbl.setText("Downloading…")
        self._run_async("download", lambda: media_backend.download(url, DL_DIR))

    def _apply_download(self, payload):
        if payload.get("error"):
            self.backend_lbl.setText(f"download failed: {payload['error']}")
        else:
            self.backend_lbl.setText(f"saved → {payload}")

    def _open_video(self):
        url = self.url_lbl.text().strip()
        if not url:
            return
        subprocess.Popen(["xdg-open", url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.backend_lbl.setText("opened in default browser")

    # ------------------------------------------------- attachments
    def _browse_attachment(self, kind):
        code, class_title = self._current
        if not code or not class_title:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose file", "",
            "Documents (*.pdf *.ppt *.pptx *.doc *.docx *.md *.txt)")
        if not path:
            return
        courses = self._courses()
        cls = courses[code]["classes"][class_title]
        cls[kind + "_path"] = path
        self._save_courses(courses)
        self._load_detail()

    def _open_attachment(self, kind):
        code, class_title = self._current
        if not code or not class_title:
            return
        courses = self._courses()
        cls = courses.get(code, {}).get("classes", {}).get(class_title, {})
        path = cls.get(kind + "_path")
        if path and os.path.exists(path):
            subprocess.Popen(["xdg-open", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ------------------------------------------------- completion
    def _on_completion_toggled(self, _state):
        if self._updating:
            return
        code, class_title = self._current
        if not code or not class_title:
            return
        completion = self._completion()
        titles = set(completion.get(code, []) or [])
        if self.complete_cb.isChecked():
            titles.add(class_title)
        else:
            titles.discard(class_title)
        completion[code] = sorted(titles)
        self.broker.set("materials.completion", completion)

    # ------------------------------------------------- notepad
    def _save_notepad(self):
        code, class_title = self._current
        if not code or not class_title:
            return
        courses = self._courses()
        cls = courses.get(code, {}).get("classes", {}).get(class_title)
        if cls is None:
            return
        cls["notepad"] = self.notepad.toPlainText()
        self._save_courses(courses)
        self.note_hint.setText("notepad saved")

    # ---------------------------------------------------- CRUD actions
    def _add_course(self):
        dialog = CourseDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        code, title = dialog.values()
        if not code:
            return
        courses = self._courses()
        if code in courses:
            QMessageBox.information(self, "Duplicate",
                                    f"Course '{code}' already exists.")
            return
        courses[code] = {"title": title or code, "classes": {}}
        self._save_courses(courses)
        self.tree.expandAll()

    def _add_class(self):
        code, _class_title = self._current_target()
        if code is None:
            QMessageBox.information(self, "Add class",
                                    "Select a course first (click its name).")
            return
        dialog = ClassDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        title = values["title"]
        if not title:
            return
        courses = self._courses()
        classes = courses[code]["classes"]
        if title in classes:
            QMessageBox.information(self, "Duplicate",
                                    f"Class '{title}' already exists.")
            return
        classes[title] = {
            "video_url": values["video_url"],
            "notes_path": values["notes_path"],
            "slides_path": values["slides_path"],
            "notepad": "",
        }
        self._save_courses(courses)

    def _edit_current(self):
        code, class_title = self._current
        if not code or not class_title:
            return
        courses = self._courses()
        cls = dict(courses.get(code, {}).get("classes", {}).get(class_title, {}) or {})
        dialog = ClassDialog(self, cls=cls)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        new_title = values["title"]
        if not new_title:
            return
        classes = courses[code]["classes"]
        old_data = classes.pop(class_title, {})
        old_data.update(values)
        if new_title != class_title:
            completion = self._completion()
            titles = completion.get(code, [])
            if class_title in titles:
                titles.remove(class_title)
                if new_title not in titles:
                    titles.append(new_title)
            completion[code] = titles
            self.broker.set("materials.completion", completion)
        classes[new_title] = old_data
        self._save_courses(courses)

    def _remove_selected(self):
        code, class_title = self._current_target()
        if code is None:
            return
        courses = self._courses()
        if class_title is None:
            answer = QMessageBox.question(
                self, "Remove course", f"Remove course '{code}' and its classes?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            courses.pop(code, None)
            completion = self._completion()
            completion.pop(code, None)
            self.broker.set_many({"materials.courses": courses,
                                  "materials.completion": completion})
            if self._selected[0] == code:
                self._selected = (None, None)
        else:
            answer = QMessageBox.question(
                self, "Remove class", f"Remove class '{class_title}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            courses[code]["classes"].pop(class_title, None)
            self._save_courses(courses)
            completion = self._completion()
            if class_title in completion.get(code, []):
                completion[code].remove(class_title)
                self.broker.set("materials.completion", completion)
            if self._selected == (code, class_title):
                self._selected = (code, None)

    # ------------------------------------------------------------ async
    def _run_async(self, tag, fn):
        def worker():
            try:
                payload = fn()
            except Exception as exc:
                payload = {"error": str(exc)}
            self._result.emit(tag, payload)

        threading.Thread(target=worker, daemon=True).start()
