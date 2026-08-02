# File Location: databroker.py
# Academic & Life Command Center — centralized state broker (Phase 1 Foundation).
#
# Every tab's state mutation flows through this broker:
#   * persists to system_state.json instantly (atomic write, no partial file)
#   * broadcasts pyqtSignals so live UI (Home Cockpit, status bars, charts)
#     redraws in real time without polling.
#
# Phase 1 deliverable: the broker itself, no tab logic yet.

import json
import os
import tempfile
import threading
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal


# ---------------------------------------------------------------------------
# Default state. Mirrors system_state.json's schema (the file structure, not
# app data). Seeded on first run / merged under whatever is already on disk,
# so new schema keys appear even when an older state file exists.
# ---------------------------------------------------------------------------
DEFAULT_STATE = {
    "__schema_version": 1,
    "__meta": {
        "created": None,
        "last_updated": None,
        "note": "Schema (structure, not app data). Tabs fill sections in later phases.",
    },
    "app": {
        "active_tab": None,
        "window": {"width": 1440, "height": 900},
    },
    "profile": {
        "student": {
            "full_name": "", "roll_no": "", "reg_no": "", "institute": "",
            "department": "", "course": "", "semester": "", "session": "",
            "email": "", "phone": "", "blood_group": "", "address": "",
            "photo_path": "", "cgpa": None,
        },
        "instructors": [],
    },
    "syllabus": {
        "active_semester": None,
        "semesters": {},
        "semester_start": None,
        "exams": [],
    },
    "attendance": {
        "routine": [],
        "records": {},
        "days_per_week": 5,
        "overrides": {},
        "holidays": [],
        "risk_threshold": 75,
    },
    "focus": {
        "productivity_log": [],
        "optimal_windows": {},
    },
    "homework": [],
    "assignments": [],
    "marks": {},
    "checklist": {
        "custom_tasks": [],
        "log": {},
    },
    "backup": {
        "keep": 20,
        "auto_backup": True,
        "last_backup": None,
        "last_backup_reason": None,
    },
    "life": {
        "daily_goals": [],
        "habits": {},
        "habit_log": {},
        "study_log": {},
    },
    "materials": {
        "courses": {},
        "completion": {},
    },
    "predictive": {
        "grade_deflection": {"status": None, "predicted_score": None, "last_run": None},
        "focus_window": {"best_block": None, "last_run": None},
        "habit_cascade": {"state": None, "days_missed": 0},
    },
    "session": {
        "user_id": None,
        "started_at": None,
    },
}


def _deep_merge(base, override):
    """Recursively merge ``override`` into a deep copy of ``base``."""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override if isinstance(override, type(base)) else override
    result = json.loads(json.dumps(base))  # deep copy of base
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class DataBroker(QObject):
    """Central, thread-safe state store for every tab in the Command Center.

    All mutations go through :meth:`set` / :meth:`set_many` / :meth:`set_section`.
    Each write is persisted to disk immediately and announced with signals.

    Signals
    -------
    state_changed(str key, object value)  : one dotted key changed
    section_changed(str name, dict section) : a whole section was updated
    state_saved(str path)                  : state written to disk
    """

    state_changed = pyqtSignal(str, object)
    section_changed = pyqtSignal(str, object)
    state_saved = pyqtSignal(str)

    def __init__(self, state_path=None, parent=None):
        super().__init__(parent)
        self._lock = threading.RLock()
        self._path = state_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "system_state.json")
        saved = self._load_file()
        self._state = _deep_merge(DEFAULT_STATE, saved)
        self._dirty = False

    # ------------------------------------------------------------------ API
    def get(self, key, default=None):
        """Read a value by dotted path, e.g. ``broker.get("app.window.width")``."""
        with self._lock:
            return _get_at(self._state, key, default)

    def set(self, key, value):
        """Set a value by dotted path and persist + broadcast instantly."""
        with self._lock:
            if _get_at(self._state, key, _MISSING) == value:
                return
            _set_at(self._state, key, value)
            self._touch_meta()
            self.save()
        section = key.split(".")[0]
        self.state_changed.emit(key, value)
        self.section_changed.emit(section, self.snapshot().get(section))

    def set_many(self, mapping):
        """Apply several dotted-key updates in one atomic write."""
        with self._lock:
            changed = {}
            for key, value in mapping.items():
                if _get_at(self._state, key, _MISSING) != value:
                    _set_at(self._state, key, value)
                    changed[key] = value
            if changed:
                self._touch_meta()
                self.save()
        for key, value in changed.items():
            self.state_changed.emit(key, value)
        for section in {k.split(".")[0] for k in changed}:
            self.section_changed.emit(section, self.snapshot().get(section))

    def set_section(self, section, updates):
        """Merge ``updates`` into a whole section (e.g. all of ``predictive``)."""
        with self._lock:
            current = self._state.setdefault(section, {})
            if not isinstance(current, dict):
                current = self._state[section] = {}
            current = _deep_merge(current, updates)
            self._state[section] = current
            self._touch_meta()
            self.save()
        self.state_changed.emit(section, current)
        self.section_changed.emit(section, current)

    def snapshot(self):
        """Return a deep copy of the whole state dict (safe to mutate)."""
        with self._lock:
            return json.loads(json.dumps(self._state))

    @property
    def state_path(self):
        """Absolute path of the state file this broker persists to."""
        return self._path

    def load_state(self, state):
        """Replace the whole state from a snapshot (used by backup restore).

        Merged under DEFAULT_STATE so missing schema keys are re-added,
        persisted atomically, then section_changed is broadcast for every
        section so all live tabs redraw from the restored data.
        """
        if not isinstance(state, dict):
            raise ValueError("state snapshot must be a dict")
        with self._lock:
            self._state = _deep_merge(DEFAULT_STATE, state)
            self._touch_meta()
            self.save()
        self.state_changed.emit("__restored", True)
        snapshot = self.snapshot()
        for section in list(snapshot.keys()):
            self.section_changed.emit(section, snapshot.get(section))

    def reset(self):
        """Restore schema defaults and persist."""
        with self._lock:
            self._state = _deep_merge(DEFAULT_STATE, {})
            self._touch_meta()
            self.save()
        self.section_changed.emit("__schema_version", self._state["__schema_version"])
        self.state_changed.emit("reset", True)

    # -------------------------------------------------------------- plumbing
    def save(self):
        """Atomic write to disk: temp file + rename, so a crash never leaves
        a half-written system_state.json."""
        with self._lock:
            self._touch_meta()
            payload = json.dumps(self._state, indent=2, ensure_ascii=False)
            directory = os.path.dirname(self._path) or "."
            fd, tmp = tempfile.mkstemp(prefix=".system_state.", suffix=".json", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                os.replace(tmp, self._path)
            except Exception:
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise
            self._dirty = False
        self.state_saved.emit(self._path)

    def _touch_meta(self):
        now = datetime.now().isoformat(timespec="seconds")
        if self._state.get("__meta") is None:
            self._state["__meta"] = {}
        if not self._state["__meta"].get("created"):
            self._state["__meta"]["created"] = now
        self._state["__meta"]["last_updated"] = now

    def _load_file(self):
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}


# ---------------------------------------------------------------------------
# Dotted-path helpers
# ---------------------------------------------------------------------------
_MISSING = object()


def _get_at(node, key, default=None):
    if not key:
        return node
    for part in key.split("."):
        if isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                return default
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return node


def _set_at(node, key, value):
    """Set a dotted path, supporting list indices, e.g.
    ``syllabus.semesters.semester_1.CSE101.topics.1.status``.
    Implicit list extension is not allowed (missing index raises KeyError)."""
    parts = key.split(".")
    for part in parts[:-1]:
        if isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                raise KeyError(f"bad list index {part!r} in {key!r}")
        else:
            nxt = node.get(part)
            if isinstance(nxt, list):
                node = nxt  # descend into an existing list unchanged
            else:
                if not isinstance(nxt, dict):
                    nxt = node[part] = {}
                node = nxt
    node[parts[-1]] = value
