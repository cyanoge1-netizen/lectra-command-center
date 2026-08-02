# -*- coding: utf-8 -*-
"""AI Notes Studio tab (Phase 12) - ported from the ERP project's studio.

One screen that turns lecture material into a polished XeLaTeX PDF:

  Left  - inputs: subject (syllabus-linked combo), topic, template, language,
          lecture index, source files + pasted text, extraction preview,
          enhancement options, AI provider settings, then "Generate".
  Right - the Vault: per-subject note bundles with open / open-folder /
          delete, backed by notes/vault.py (index.json is the source of truth).

Generation runs on a worker thread so the UI stays responsive; progress is
streamed into the log. Everything stays offline unless an AI provider is
configured (notes/ai_client.py).
"""
import os
import shutil

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QListWidget, QPlainTextEdit, QCheckBox,
    QSpinBox, QSplitter, QScrollArea, QFrame, QDialog, QFileDialog,
    QMessageBox,
)

from notes.ai_notes_pipeline import AINotesPipeline, PipelineError
from notes.ai_client import AIClient, PROVIDERS
from notes.settings import AppSettings, LANGUAGES
from ui_helpers import make_course_combo

TITLE_FONT = "font-size: 14px; font-weight: 700;"


class _GenerateWorker(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, pipeline, kwargs):
        super().__init__()
        self._pipeline = pipeline
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._pipeline.generate(
                progress=self.progress.emit, **self._kwargs)
            self.done.emit(result)
        except PipelineError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit("Unexpected error: {0}".format(e))


class _PreviewDialog(QDialog):
    """Read-only view of extracted text (OCR sanity check before compiling)."""

    def __init__(self, sections, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Extracted text")
        self.resize(640, 480)
        layout = QVBoxLayout(self)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        for name, content in sections:
            text.appendPlainText("==== {0} ====".format(name))
            text.appendPlainText(content)
            text.appendPlainText("")
        layout.addWidget(text, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)


class NotesTab(QWidget):
    def __init__(self, broker, parent=None):
        super().__init__(parent)
        self.broker = broker
        self.pipeline = AINotesPipeline(user_id=1)
        self.settings = AppSettings(user_id=1)
        self._worker = None
        self._build_ui()
        self._load_settings_into_ui()
        broker.section_changed.connect(self._on_section_changed)
        self._refresh_vault()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_studio())
        splitter.addWidget(self._build_vault())
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def _section_title(self, text):
        label = QLabel(text)
        label.setProperty("role", "active")
        label.setStyleSheet(TITLE_FONT)
        return label

    def _build_studio(self):
        panel = QFrame()
        panel.setProperty("panel", True)
        root = QVBoxLayout(panel)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        root.addWidget(self._section_title("New note"))

        form = QFormLayout()
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.subject = make_course_combo(self.broker)
        self.topic = QLineEdit()
        self.topic.setPlaceholderText("e.g. Pointers & Memory (optional)")

        self.template = QComboBox()
        self.template.addItems(self.pipeline.available_templates())

        self.language = QComboBox()
        for code, info in LANGUAGES.items():
            self.language.addItem(info["label"], code)

        self.index_mode = QComboBox()
        self.index_mode.addItem("Auto (next number)", "auto")
        self.index_mode.addItem("Manual", "manual")
        self.index_manual = QSpinBox()
        self.index_manual.setRange(1, 999)
        self.index_manual.setValue(1)
        self.index_mode.currentIndexChanged.connect(
            lambda _: self.index_manual.setEnabled(
                self.index_mode.currentData() == "manual"))
        index_row = QHBoxLayout()
        index_row.addWidget(self.index_mode, 1)
        index_row.addWidget(self.index_manual)
        index_box = QWidget()
        index_box.setLayout(index_row)

        form.addRow("Subject", self.subject)
        form.addRow("Topic", self.topic)
        form.addRow("Template", self.template)
        form.addRow("Language", self.language)
        form.addRow("Lecture index", index_box)
        root.addLayout(form)

        root.addWidget(QLabel("Sources"))
        self.file_list = QListWidget()
        self.file_list.setFixedHeight(84)
        root.addWidget(self.file_list)
        src_row = QHBoxLayout()
        add_files = QPushButton("Add files…")
        add_files.clicked.connect(self._add_files)
        rm_files = QPushButton("Remove selected")
        rm_files.clicked.connect(self._remove_files)
        self.preview_btn = QPushButton("Extract & preview")
        self.preview_btn.clicked.connect(self._preview)
        for b in (add_files, rm_files, self.preview_btn):
            src_row.addWidget(b)
        src_row.addStretch(1)
        root.addLayout(src_row)

        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText("or paste the lecture text / markdown here…")
        self.paste.setFixedHeight(70)
        root.addWidget(self.paste)

        opts_title = self._section_title("Enhancements")
        root.addWidget(opts_title)
        grid = QVBoxLayout()
        self.opt_fix = QCheckBox("Fix grammar & spelling")
        self.opt_graphs = QCheckBox("Add graphs (pgfplots)")
        self.opt_explain = QCheckBox("Add explanations")
        self.opt_style = QCheckBox("Preserve original style")
        self.opt_style.setChecked(True)
        self.opt_tikz = QCheckBox("Add TikZ diagrams")
        self.opt_translate = QCheckBox("Translate (AI)")
        self.opt_translate_offline = QCheckBox("Translate offline (MarianMT)")
        two = QHBoxLayout()
        left = QVBoxLayout()
        right = QVBoxLayout()
        for cb in (self.opt_fix, self.opt_graphs, self.opt_explain, self.opt_style):
            left.addWidget(cb)
        for cb in (self.opt_tikz, self.opt_translate, self.opt_translate_offline):
            right.addWidget(cb)
        two.addLayout(left)
        two.addLayout(right)
        grid.addLayout(two)
        root.addLayout(grid)

        self.custom_prompt = QLineEdit()
        self.custom_prompt.setPlaceholderText("Custom instruction (optional)")
        root.addWidget(self.custom_prompt)

        ai_title = self._section_title("AI provider")
        root.addWidget(ai_title)
        ai_form = QFormLayout()
        self.ai_provider = QComboBox()
        for key, info in PROVIDERS.items():
            self.ai_provider.addItem(info["label"], key)
        self.ai_model = QLineEdit()
        self.ai_key = QLineEdit()
        self.ai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_base = QLineEdit()
        self.ai_status = QLabel("")
        self.ai_status.setProperty("muted", True)
        ai_form.addRow("Provider", self.ai_provider)
        ai_form.addRow("Model", self.ai_model)
        ai_form.addRow("API key", self.ai_key)
        ai_form.addRow("Base URL", self.ai_base)
        root.addLayout(ai_form)
        save_ai = QPushButton("Save AI settings")
        save_ai.clicked.connect(self._save_ai_settings)
        root.addWidget(save_ai)
        root.addWidget(self.ai_status)

        self.generate_btn = QPushButton("Generate note (PDF)")
        self.generate_btn.setProperty("role", "active")
        self.generate_btn.clicked.connect(self._generate)
        root.addWidget(self.generate_btn)

        log_title = QLabel("Progress")
        log_title.setProperty("muted", True)
        root.addWidget(log_title)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(96)
        self.log.setProperty("mono", True)
        root.addWidget(self.log)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(panel)
        return scroll

    def _build_vault(self):
        panel = QFrame()
        panel.setProperty("panel", True)
        root = QVBoxLayout(panel)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        root.addWidget(self._section_title("Vault"))

        filter_row = QHBoxLayout()
        self.vault_filter = QComboBox()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_vault)
        filter_row.addWidget(self.vault_filter, 1)
        filter_row.addWidget(refresh)
        root.addLayout(filter_row)

        self.vault_list = QListWidget()
        root.addWidget(self.vault_list, 1)

        btn_row = QHBoxLayout()
        open_pdf = QPushButton("Open PDF")
        open_pdf.clicked.connect(self._open_pdf)
        open_folder = QPushButton("Open folder")
        open_folder.clicked.connect(self._open_folder)
        delete = QPushButton("Delete")
        delete.clicked.connect(self._delete_entry)
        for b in (open_pdf, open_folder, delete):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self.vault_hint = QLabel(
            "Notes you generate are kept here as portable bundles: PDF, "
            "source.tex, meta.json, transcript.txt. They are included in "
            "your backups.")
        self.vault_hint.setProperty("muted", True)
        self.vault_hint.setWordWrap(True)
        self.vault_hint.setVisible(False)
        root.addWidget(self.vault_hint)
        return panel

    # ----------------------------------------------------------- settings
    def _load_settings_into_ui(self):
        s = self.settings
        subject = s.get("subject") or ""
        if subject and self.subject.findText(subject) >= 0:
            self.subject.setCurrentText(subject)
        template = s.get("template") or "ai_notes.tex"
        idx = self.template.findText(template)
        if idx >= 0:
            self.template.setCurrentIndex(idx)
        lang = s.get("language") or "english"
        idx = self.language.findData(lang)
        if idx >= 0:
            self.language.setCurrentIndex(idx)
        mode = s.get("lecture_index_mode") or "auto"
        idx = self.index_mode.findData(mode)
        if idx >= 0:
            self.index_mode.setCurrentIndex(idx)
        self.index_manual.setValue(int(s.get("lecture_index_manual") or 1))
        self.index_manual.setEnabled(mode == "manual")
        opts = s.get("request_options") or {}
        self.opt_fix.setChecked(bool(opts.get("fix_grammar")))
        self.opt_graphs.setChecked(bool(opts.get("add_graphs")))
        self.opt_explain.setChecked(bool(opts.get("add_explanations")))
        self.opt_style.setChecked(bool(opts.get("preserve_style", True)))
        self.opt_tikz.setChecked(bool(opts.get("add_tikz")))
        self.opt_translate.setChecked(bool(opts.get("translate")))
        self.opt_translate_offline.setChecked(bool(opts.get("translate_offline")))
        self.custom_prompt.setText(s.get("custom_prompt") or "")
        provider = s.get("ai_provider") or "offline"
        idx = self.ai_provider.findData(provider)
        if idx >= 0:
            self.ai_provider.setCurrentIndex(idx)
        self.ai_model.setText(s.get("ai_model") or "")
        self.ai_key.setText(s.get("ai_api_key") or "")
        self.ai_base.setText(s.get("ai_base_url") or "")
        self._refresh_ai_status()

    def _save_settings(self):
        s = self.settings
        s.set("subject", self.subject.currentText().strip())
        s.set("template", self.template.currentText())
        s.set("language", self.language.currentData())
        s.set("lecture_index_mode", self.index_mode.currentData())
        s.set("lecture_index_manual", self.index_manual.value())
        opts = {
            "fix_grammar": self.opt_fix.isChecked(),
            "add_graphs": self.opt_graphs.isChecked(),
            "add_explanations": self.opt_explain.isChecked(),
            "preserve_style": self.opt_style.isChecked(),
            "add_tikz": self.opt_tikz.isChecked(),
            "translate": self.opt_translate.isChecked(),
            "translate_offline": self.opt_translate_offline.isChecked(),
        }
        s.set("request_options", opts)
        s.set("custom_prompt", self.custom_prompt.text())
        s.save()

    def _save_ai_settings(self):
        s = self.settings
        s.set("ai_provider", self.ai_provider.currentData())
        s.set("ai_model", self.ai_model.text().strip())
        s.set("ai_api_key", self.ai_key.text().strip())
        s.set("ai_base_url", self.ai_base.text().strip())
        s.save()
        self._refresh_ai_status()
        self._status_message("AI settings saved")

    def _refresh_ai_status(self):
        client = self._ai_client()
        status = client.describe()
        status += "  ·  " + self.pipeline.translator.describe()
        if not self.pipeline.ocr.is_available():
            status += "  ·  OCR: tesseract not installed"
        else:
            status += "  ·  OCR ready"
        self.ai_status.setText(status)

    def _ai_client(self):
        return AIClient(
            provider=self.ai_provider.currentData(),
            api_key=self.ai_key.text().strip(),
            model=self.ai_model.text().strip(),
            base_url=self.ai_base.text().strip(),
        )

    # ------------------------------------------------------------ sources
    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add lecture sources",
            "", "Sources (*.md *.txt *.markdown *.text *.png *.jpg *.jpeg "
                "*.bmp *.webp *.tif *.tiff *.heic *.pdf)")
        seen = set(self._source_paths())
        for path in paths:
            if path not in seen:
                seen.add(path)
                self.file_list.addItem(path)

    def _source_paths(self):
        return [self.file_list.item(i).text()
                for i in range(self.file_list.count())]

    def _remove_files(self):
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))

    def _preview(self):
        paths = self._source_paths()
        pasted = self.paste.toPlainText()
        if not paths and not pasted.strip():
            QMessageBox.information(self, "Nothing to preview",
                                    "Add files or paste some text first.")
            return
        try:
            sections = self.pipeline.extract_preview(
                paths, pasted, self.language.currentData())
        except PipelineError as e:
            QMessageBox.warning(self, "Extraction failed", str(e))
            return
        _PreviewDialog(sections, self).exec()

    # ------------------------------------------------------------ generate
    def _gather_kwargs(self):
        paths = self._source_paths()
        pasted = self.paste.toPlainText()
        if not paths and not pasted.strip():
            raise PipelineError("Add some input first (files or pasted text).")
        if not self.subject.currentText().strip():
            raise PipelineError("Choose a subject first.")
        options = {
            "fix_grammar": self.opt_fix.isChecked(),
            "add_graphs": self.opt_graphs.isChecked(),
            "add_explanations": self.opt_explain.isChecked(),
            "preserve_style": self.opt_style.isChecked(),
            "add_tikz": self.opt_tikz.isChecked(),
            "translate": self.opt_translate.isChecked(),
            "translate_offline": self.opt_translate_offline.isChecked(),
        }
        return {
            "subject": self.subject.currentText().strip(),
            "template": self.template.currentText(),
            "language": self.language.currentData(),
            "font_folder": "",
            "topic": self.topic.text().strip(),
            "input_paths": paths,
            "pasted_text": pasted,
            "options": options,
            "custom_prompt": self.custom_prompt.text().strip(),
            "lecture_index_mode": self.index_mode.currentData(),
            "lecture_index_manual": self.index_manual.value(),
            "ai_client": self._ai_client(),
        }

    def _generate(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self._save_settings()
        try:
            kwargs = self._gather_kwargs()
        except PipelineError as e:
            QMessageBox.warning(self, "Missing input", str(e))
            return
        self.log.clear()
        self.generate_btn.setEnabled(False)
        self._worker = _GenerateWorker(self.pipeline, kwargs)
        self._worker.progress.connect(self.log.appendPlainText)
        self._worker.done.connect(self._on_generate_done)
        self._worker.failed.connect(self._on_generate_failed)
        self._worker.start()

    def _on_generate_done(self, result):
        self.generate_btn.setEnabled(True)
        entry = result.get("entry") or {}
        self.log.appendPlainText(
            "Done: {0} ({1} pages)".format(
                os.path.basename(result.get("pdf_path", "")),
                entry.get("pages", 0)))
        self._status_message("Note saved to the Vault")
        self._refresh_vault()

    def _on_generate_failed(self, message):
        self.generate_btn.setEnabled(True)
        self.log.appendPlainText("Failed: {0}".format(message))
        QMessageBox.warning(self, "Note generation failed", message)

    def _status_message(self, text):
        window = self.window()
        status = getattr(window, "statusBar", None)
        if status and callable(status):
            status().showMessage(text, 5000)

    # -------------------------------------------------------------- vault
    def _refresh_vault(self):
        current = self.vault_filter.currentData()
        subjects = self.pipeline.vault.subjects()
        self.vault_filter.blockSignals(True)
        self.vault_filter.clear()
        self.vault_filter.addItem("All subjects", None)
        for subject in subjects:
            self.vault_filter.addItem(subject, subject)
        idx = self.vault_filter.findData(current)
        self.vault_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.vault_filter.blockSignals(False)
        self._reload_entries()

    def _reload_entries(self):
        subject = self.vault_filter.currentData()
        entries = self.pipeline.vault.entries(subject)
        self.vault_list.clear()
        for entry in entries:
            self.vault_list.addItem(
                "{0}  #{1}  {2}  ({3} pp)".format(
                    entry.get("subject", "—"),
                    int(entry.get("lecture_index", 0) or 0),
                    entry.get("title") or "",
                    entry.get("pages", 0)))
        self.vault_hint.setVisible(not entries)

    def _selected_entry(self):
        row = self.vault_list.currentRow()
        if row < 0:
            return None
        subject = self.vault_filter.currentData()
        entries = self.pipeline.vault.entries(subject)
        if row >= len(entries):
            return None
        return entries[row]

    def _open_pdf(self):
        entry = self._selected_entry()
        if not entry:
            return
        path = entry.get("pdf_path", "")
        if path and os.path.isfile(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.information(self, "No PDF",
                                    "The PDF for this note is missing.")

    def _open_folder(self):
        entry = self._selected_entry()
        if not entry:
            return
        folder = entry.get("folder") or os.path.dirname(entry.get("pdf_path", ""))
        if folder and os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        else:
            QMessageBox.information(self, "No folder",
                                    "The bundle folder is missing.")

    def _delete_entry(self):
        entry = self._selected_entry()
        if not entry:
            return
        title = entry.get("title") or "this note"
        ret = QMessageBox.question(
            self, "Delete note",
            "Delete \"{0}\" (#{1}, {2}) and its files?".format(
                title, int(entry.get("lecture_index", 0) or 0),
                entry.get("subject", "—")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return
        self.pipeline.vault.remove_entry(entry.get("id"))
        folder = entry.get("folder")
        if folder and os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
        self._status_message("Note deleted")
        self._refresh_vault()

    # ------------------------------------------------------------- broker
    def _on_section_changed(self, section, _value):
        if section != "syllabus":
            return
        current = self.subject.currentText()
        self.subject.blockSignals(True)
        self.subject.clear()
        self.subject.addItems(self._syllabus_codes())
        if current:
            self.subject.setCurrentText(current)
        self.subject.blockSignals(False)

    def _syllabus_codes(self):
        from ui_helpers import course_codes
        return course_codes(self.broker)
