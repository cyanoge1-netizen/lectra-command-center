# -*- coding: utf-8 -*-
"""Backup & Restore dialog (hardening feature).

Lists backups from the BackupManager newest-first, shows a per-backup summary
(record counts), lets the user create a manual backup on the spot, and restores
a selected backup after a confirm dialog. Restore runs BackupManager.restore,
which reloads the broker (every tab redraws via load_state) and rewrites the
referenced files. Corrupt backups are refused at preview time.
"""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
)


def _human_size(n):
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class BackupRestoreDialog(QDialog):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Backup & Restore")
        self.setMinimumSize(640, 380)
        layout = QVBoxLayout(self)

        heading = QLabel("Command Center backups")
        heading.setProperty("role", "active")
        heading.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(heading)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Backup", "Date / time", "Reason", "Size"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_select)
        layout.addWidget(self.table, 1)

        self.summary_lbl = QLabel("")
        self.summary_lbl.setProperty("mono", True)
        self.summary_lbl.setWordWrap(True)
        layout.addWidget(self.summary_lbl)

        buttons = QHBoxLayout()
        for text, fn in (("Backup now", self._create),
                         ("Refresh", self._refresh_list),
                         ("Restore selected…", self._restore),
                         ("Close", self.accept)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            buttons.addWidget(b)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._infos = []
        self._refresh_list()

    # ------------------------------------------------------------- list
    def _refresh_list(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self._infos = self.manager.list()
        for info in self._infos:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [info.name,
                      info.created.strftime("%Y-%m-%d %H:%M"),
                      info.reason, _human_size(info.size)]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, info)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        if self._infos:
            self.table.selectRow(0)
        self._on_select()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def _on_select(self):
        info = self._selected()
        if not info:
            self.summary_lbl.setText("No backups on disk yet.")
            return
        lines = [f"{info.name}  ({_human_size(info.size)})"]
        s = info.summary or {}
        parts = [f"{s.get('courses', 0)} courses",
                 f"{s.get('topics', 0)} topics",
                 f"{s.get('exams', 0)} exams",
                 f"{s.get('homework', 0)} homework",
                 f"{s.get('assignments', 0)} assignments",
                 f"{s.get('custom_tasks', 0)} custom tasks"]
        lines.append("  ·  ".join(parts))
        self.summary_lbl.setText("\n".join(lines))

    # ------------------------------------------------------------ actions
    def _create(self):
        try:
            path = self.manager.create(reason="manual")
        except Exception as exc:
            QMessageBox.warning(self, "Backup failed", str(exc))
            return
        self._refresh_list()
        QMessageBox.information(self, "Backup created",
                                f"Saved\n{os.path.basename(path)}")

    def _restore(self):
        info = self._selected()
        if not info:
            QMessageBox.information(self, "Restore",
                                    "Select a backup first.")
            return
        try:
            manifest = self.manager.preview(info.path)
        except ValueError as exc:
            QMessageBox.warning(self, "Corrupt backup", str(exc))
            return
        s = info.summary or {}
        n_files = len(manifest["files"])
        n_data = len(manifest["data_files"])
        msg = (
            f"Restore backup {info.name}?\n\n"
            f"Created {info.created.strftime('%Y-%m-%d %H:%M')} · {info.reason}\n"
            f"Contains: {s.get('courses', 0)} courses · {s.get('topics', 0)} topics · "
            f"{s.get('custom_tasks', 0)} custom tasks\n"
            f"Referenced files: {n_files} · data seeds: {n_data}\n\n"
            "ALL current data will be replaced by this snapshot. "
            "Consider backing up first.")
        if QMessageBox.question(self, "Confirm restore", msg) != \
                QMessageBox.StandardButton.Yes:
            return
        try:
            result = self.manager.restore(info.path)
        except Exception as exc:
            QMessageBox.critical(self, "Restore failed", str(exc))
            return
        summary = result.get("summary", {}) or {}
        extra = ""
        if result.get("_warnings"):
            extra = f"\n\nWarnings:\n" + "\n".join(result["_warnings"][:5])
        QMessageBox.information(
            self, "Restore complete",
            f"Restored {info.name}\n"
            f"courses={summary.get('courses', 0)} · topics={summary.get('topics', 0)} · "
            f"custom tasks={summary.get('custom_tasks', 0)}\n"
            f"files written: {result.get('files_restored', 0)}"
            + extra)
