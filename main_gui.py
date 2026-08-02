# File Location: main_gui.py
# Academic & Life Command Center — skeleton window (Phase 1 Foundation).
#
# Empty tab containers wired to the DataBroker. No tab logic yet:
# every phase (3–8) fills one of these placeholder tabs and talks to the
# rest of the app exclusively through the broker.
#
#   Phase 3 → Home Cockpit       Phase 8 → Materials
#   Phase 4 → Profiles           Phase 9 → Today Brief (first tab)
#   Phase 5 → Syllabus Engine    Phase 10 → Marks & Trends
#   Phase 6 → Attendance         Phase 11 → Checklist (today/attendance/marks build)
#   Phase 7 → Life & Daily Goals
#
# Run:  python3 main_gui.py

import os
import sys
from datetime import datetime

from PyQt6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel,
    QStatusBar, QPushButton, QMessageBox,
)

from databroker import DataBroker
import styles


def _make_predictive_engine():
    """Import + train the Phase 2 engine. Never fatal: if scikit-learn or the
    data files are unavailable the engine reports ready=False with a reason
    (flagged, never fabricated). Returns (engine, reason_or_None)."""
    try:
        from predictive_engine import PredictiveEngine
        return PredictiveEngine(), None
    except Exception as exc:  # ImportError, bad data, etc.
        return None, str(exc)


# (future phase, tab title) — Today Brief sits first as the daily operational view
PHASE_TABS = [
    (9, "Today Brief"),
    (3, "Home Cockpit"),
    (4, "Profiles"),
    (5, "Syllabus Engine"),
    (6, "Attendance"),
    (7, "Life & Daily Goals"),
    (8, "Materials"),
    (10, "Marks & Trends"),
    (11, "Checklist"),
]


class PlaceholderTab(QWidget):
    """Empty tab shell. Later phases replace the body; for now it proves the
    broker connection by echoing the latest state it receives."""

    def __init__(self, broker, phase, title, parent=None):
        super().__init__(parent)
        self.broker = broker
        self._title = title
        self.setProperty("panel", True)
        root = QVBoxLayout(self)
        root.setSpacing(8)

        header = QLabel(f"Phase {phase} · {title}")
        header.setProperty("role", "active")
        header.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(header)

        body = QLabel(f"Empty tab container — \"{title}\" ships in Phase {phase}.")
        body.setProperty("muted", True)
        root.addWidget(body)

        self.broker_readout = QLabel("broker: no updates yet")
        self.broker_readout.setProperty("mono", True)
        self.broker_readout.setProperty("muted", True)
        root.addWidget(self.broker_readout)
        root.addStretch(1)

        broker.state_changed.connect(self._on_state_changed)

    def _on_state_changed(self, key, value):
        self.broker_readout.setText(f"broker: {key} = {value!r}")


class MainWindow(QMainWindow):
    def __init__(self, broker=None, parent=None):
        super().__init__(parent)
        self.broker = broker or DataBroker()
        self.predictive_engine, self._engine_reason = _make_predictive_engine()
        self.setWindowTitle("Lectra - Academic & Life Command Center (Beta 0.5)")
        styles.apply_theme(self)
        self._build_ui()
        self._wire_broker()
        self._stamp_session()
        self._push_predictive()
        self._auto_backup_on_start()
        self._restore_window()

    # ------------------------------------------------------------- UI setup
    def _build_ui(self):
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        for phase, title in PHASE_TABS:
            if phase == 9:
                from today_brief_tab import TodayBriefTab
                widget = TodayBriefTab(self.broker)
            elif phase == 3:
                from home_cockpit import HomeCockpitTab
                widget = HomeCockpitTab(self.broker, self.predictive_engine)
            elif phase == 4:
                from profiles_tab import ProfilesTab
                widget = ProfilesTab(self.broker)
            elif phase == 5:
                from syllabus_tab import SyllabusTab
                widget = SyllabusTab(self.broker)
            elif phase == 6:
                from attendance_tab import AttendanceTab
                widget = AttendanceTab(self.broker)
            elif phase == 7:
                from life_tab import LifeTab
                widget = LifeTab(self.broker)
            elif phase == 8:
                from materials_tab import MaterialsTab
                widget = MaterialsTab(self.broker)
            elif phase == 10:
                from marks_trends_tab import MarksTrendsTab
                widget = MarksTrendsTab(self.broker)
            elif phase == 11:
                from syllabus_checklist_tab import SyllabusChecklistTab
                widget = SyllabusChecklistTab(self.broker)
            else:
                widget = PlaceholderTab(self.broker, phase, title)
            self.tabs.addTab(widget, title)
        self.setCentralWidget(self.tabs)
        for i in range(min(9, self.tabs.count())):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self,
                      activated=lambda i=i: self.tabs.setCurrentIndex(i))

        from backup_manager import BackupManager
        self.backup_manager = BackupManager(broker=self.broker)

        bar = QStatusBar()
        self.setStatusBar(bar)
        self.last_backup_lbl = QLabel("backup: none yet")
        self.last_backup_lbl.setProperty("muted", True)
        bar.addPermanentWidget(self.last_backup_lbl)
        backup_btn = QPushButton("Backup")
        backup_btn.clicked.connect(self._backup_now)
        restore_btn = QPushButton("Restore…")
        restore_btn.clicked.connect(self._restore_backup)
        bar.addPermanentWidget(backup_btn)
        bar.addPermanentWidget(restore_btn)
        bar.showMessage("Command Center · Phases 1–11 wired")
        self._refresh_backup_label()

    # ------------------------------------------------------- broker wiring
    def _wire_broker(self):
        # Always open on Today Brief (tab 0); the active tab is intentionally
        # NOT persisted so every launch starts with the daily overview.
        self.broker.state_changed.connect(self._on_broker_state)
        self.broker.state_saved.connect(self._on_broker_saved)

    def _on_broker_state(self, key, value):
        self.statusBar().showMessage(f"broker: {key} = {value!r}", 4000)

    def _on_broker_saved(self, path):
        self.statusBar().showMessage(f"saved → {path}", 2000)

    # ------------------------------------------------ Phase 2: predictive
    def _push_predictive(self):
        engine = self.predictive_engine

        if engine is None:
            self.broker.set_section("predictive", {
                "grade_deflection": {"model_ready": False, "reason": self._engine_reason,
                                     "status": None, "predicted_score": None,
                                     "last_run": None},
                "focus_window": {"model_ready": False, "reason": self._engine_reason,
                                 "best_block": None, "last_run": None},
                "habit_cascade": {"state": "LOW", "days_missed": 0},
            })
            self.statusBar().showMessage(
                f"Predictive engine unavailable: {self._engine_reason}", 8000)
            return

        report = engine.predict_all()
        self.broker.set_section("predictive", report)

        status = []
        if engine.grade_ready:
            status.append(f"grade R\u00b2={engine.grade_metrics['r2']:.2f}")
        if engine.focus_ready:
            status.append(f"focus R\u00b2={engine.focus_metrics['r2']:.2f}")
        self.statusBar().showMessage(
            "Predictive engine ready (" + ", ".join(status) + ") · all phases", 8000)

    # ------------------------------------------------------------ geometry
    def _stamp_session(self):
        if not self.broker.get("session.started_at"):
            from datetime import datetime
            self.broker.set("session.started_at",
                            datetime.now().isoformat(timespec="seconds"))

    # ------------------------------------------------------ backup / restore
    def _refresh_backup_label(self):
        cfg = self.broker.get("backup", {}) or {}
        last = cfg.get("last_backup")
        if not last:
            self.last_backup_lbl.setText("backup: none yet")
            self.last_backup_lbl.setProperty("role", "muted")
        else:
            self.last_backup_lbl.setText(
                f"backup: {last} ({cfg.get('last_backup_reason', '')})")
            self.last_backup_lbl.setProperty("role", "active")
        self.last_backup_lbl.style().unpolish(self.last_backup_lbl)
        self.last_backup_lbl.style().polish(self.last_backup_lbl)

    def _auto_backup_on_start(self):
        cfg = self.broker.get("backup", {}) or {}
        if not cfg.get("auto_backup", True):
            return
        last = cfg.get("last_backup")
        if last and str(last)[:10] == datetime.now().isoformat()[:10]:
            return
        try:
            self.backup_manager.create(reason="auto-daily")
        except Exception as exc:
            self.statusBar().showMessage(f"auto-backup failed: {exc}", 8000)
            return
        self._refresh_backup_label()
        self.statusBar().showMessage("daily auto-backup saved", 4000)

    def _backup_now(self):
        try:
            path = self.backup_manager.create(reason="manual")
        except Exception as exc:
            QMessageBox.warning(self, "Backup failed", str(exc))
            return
        self._refresh_backup_label()
        self.statusBar().showMessage(f"backup saved → {os.path.basename(path)}",
                                     5000)

    def _restore_backup(self):
        from backup_dialog import BackupRestoreDialog
        dialog = BackupRestoreDialog(self.backup_manager, self)
        dialog.exec()
        self._refresh_backup_label()

    def _restore_window(self):
        width = self.broker.get("app.window.width", 1440)
        height = self.broker.get("app.window.height", 900)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
            width = min(int(width), geometry.width())
            height = min(int(height), geometry.height())
        self.resize(int(width), int(height))

    def closeEvent(self, event):
        self.broker.set_many({
            "app.window.width": self.width(),
            "app.window.height": self.height(),
        })
        cfg = self.broker.get("backup", {}) or {}
        if cfg.get("auto_backup", True):
            try:
                self.backup_manager.create(reason="auto-close")
            except Exception:
                pass
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    styles.apply_theme(app)
    broker = DataBroker()
    window = MainWindow(broker)
    window.show()
    sys.exit(app.exec())


def _force_english_digits():
    """Keep numeric widgets in English digits even when the OS locale is
    Bengali (LC_NUMERIC=bn_BD makes Qt render 0-9 as ০-৯)."""
    from PyQt6.QtCore import QLocale
    QLocale.setDefault(
        QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))


if __name__ == "__main__":
    _force_english_digits()
    main()
