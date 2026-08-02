# -*- coding: utf-8 -*-
# File Location: backup_manager.py
# Academic & Life Command Center — strong backup & restore (hardening feature).
#
# Every backup is a self-contained ZIP written to backups/ next to the state
# file (so temp/test brokers back up into their own directory):
#   * system_state.json     — full broker snapshot
#   * files/<NNN>_<name>    — every user file the app points at (student +
#                             instructor photos, notes, slides), deduped
#   * data/<name>           — copies of the data/ seeds (sample syllabus, CSVs)
#   * manifest.json         — created / reason / summary counts / file map
#
# create()  -> timestamped backup + rotation (keep newest N)
# list()    -> newest-first BackupInfo rows (reads manifest for the summary)
# preview() -> validate a backup ZIP, return its manifest (raises ValueError)
# restore() -> validate, reload the broker from the snapshot (load_state, so
#              every tab redraws) and write referenced files back to disk
#
# Backups are atomic (tmp + rename) and corruption-checked on preview/restore.
# No new runtime dependencies (stdlib zipfile / json / dataclasses only).

import json
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime

BACKUP_PREFIX = "backup"
NAME_RE = re.compile(
    r"^backup_(\d{8})_(\d{6})_(\d{6})_([A-Za-z0-9_-]+)\.zip$")


@dataclass
class BackupInfo:
    name: str
    path: str
    created: datetime
    reason: str
    size: int
    summary: dict


def _sanitize_reason(reason):
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "-", str(reason or "backup"))
    return cleaned or "backup"


def collect_referenced_files(snapshot):
    """Every existing file the app points at (photos, notes, slides)."""
    files = []

    def add(path):
        if isinstance(path, str) and path.strip():
            files.append(path.strip())

    profile = snapshot.get("profile", {}) or {}
    student = profile.get("student", {}) or {}
    add(student.get("photo_path"))
    for inst in (profile.get("instructors", []) or []):
        if isinstance(inst, dict):
            add(inst.get("photo_path"))
    for course in ((snapshot.get("materials", {}) or {})
                   .get("courses", {}) or {}).values():
        if not isinstance(course, dict):
            continue
        for cls in (course.get("classes", {}) or {}).values():
            if isinstance(cls, dict):
                add(cls.get("notes_path"))
                add(cls.get("slides_path"))
    seen, out = set(), []
    for f in files:
        f = os.path.abspath(f)
        if f in seen or not os.path.isfile(f):
            continue
        seen.add(f)
        out.append(f)
    return out


def snapshot_summary(snapshot):
    """Human-readable counts for the manifest and restore confirm dialog."""
    syllabus = snapshot.get("syllabus", {}) or {}
    sems = syllabus.get("semesters", {}) or {}
    courses = sum(len(v or {}) for v in sems.values())
    topics = sum(
        1
        for sem in sems.values()
        for c in (sem or {}).values()
        if isinstance(c, dict)
        for t in (c.get("topics", []) or [])
        if isinstance(t, dict))
    checklist = snapshot.get("checklist", {}) or {}
    life = snapshot.get("life", {}) or {}
    return {
        "semesters": len(sems),
        "courses": courses,
        "topics": topics,
        "exams": len(syllabus.get("exams", []) or []),
        "homework": len(snapshot.get("homework", []) or []),
        "assignments": len(snapshot.get("assignments", []) or []),
        "custom_tasks": len(checklist.get("custom_tasks", []) or []),
        "log_days": len(checklist.get("log", {}) or {}),
        "routine": len((snapshot.get("attendance", {}) or {})
                       .get("routine", []) or []),
        "habits": len(life.get("habits", {}) or {}),
        "materials_courses": len((snapshot.get("materials", {}) or {})
                                 .get("courses", {}) or {}),
    }


class BackupManager:
    def __init__(self, broker=None, backups_dir=None, keep=None):
        self.broker = broker
        self._dir = os.path.abspath(backups_dir or self._default_dir())
        self.keep = keep or self._default_keep()

    # ------------------------------------------------------------ config
    def _default_dir(self):
        if self.broker is not None:
            return os.path.join(
                os.path.dirname(os.path.abspath(self.broker.state_path)),
                "backups")
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "backups")

    def _default_keep(self):
        if self.broker is not None:
            cfg = self.broker.get("backup", {}) or {}
            keep = cfg.get("keep")
            if isinstance(keep, int) and keep > 0:
                return keep
        return 20

    @property
    def dir(self):
        return self._dir

    # ------------------------------------------------------------ create
    def create(self, reason="manual"):
        """Write a timestamped backup ZIP; returns its path."""
        if self.broker is None:
            raise RuntimeError("BackupManager has no broker to snapshot")
        snapshot = self.broker.snapshot()
        now = datetime.now()
        os.makedirs(self._dir, exist_ok=True)
        name = (f"{BACKUP_PREFIX}_{now.strftime('%Y%m%d_%H%M%S_%f')}_"
                f"{_sanitize_reason(reason)}.zip")
        path = os.path.join(self._dir, name)
        tmp = path + ".tmp"

        manifest = {
            "created": now.isoformat(timespec="seconds"),
            "reason": reason,
            "summary": snapshot_summary(snapshot),
            "files": [],
            "data_files": [],
        }
        try:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(
                    "system_state.json",
                    json.dumps(snapshot, indent=2, ensure_ascii=False))
                for i, src in enumerate(collect_referenced_files(snapshot)):
                    stored = f"files/{i:03d}_{os.path.basename(src)}"
                    zf.write(src, stored)
                    manifest["files"].append({"src": src, "stored": stored})
                data_dir = os.path.join(os.path.dirname(self._dir), "data")
                if os.path.isdir(data_dir):
                    for fname in sorted(os.listdir(data_dir)):
                        full = os.path.join(data_dir, fname)
                        if os.path.isfile(full):
                            zf.write(full, f"data/{fname}")
                            manifest["data_files"].append(
                                {"src": full, "stored": f"data/{fname}"})
                zf.writestr("manifest.json",
                            json.dumps(manifest, indent=2,
                                       ensure_ascii=False))
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

        self._update_last_backup(now, reason)
        self.rotate()
        return path

    def _update_last_backup(self, stamp, reason):
        if self.broker is not None:
            self.broker.set_many({
                "backup.last_backup": stamp.isoformat(timespec="seconds"),
                "backup.last_backup_reason": reason,
            })

    # -------------------------------------------------------------- list
    def list(self):
        """Newest-first list of backups on disk."""
        if not os.path.isdir(self._dir):
            return []
        infos = []
        for name in sorted(os.listdir(self._dir), reverse=True):
            if not name.endswith(".zip"):
                continue
            m = NAME_RE.match(name)
            if not m:
                continue
            path = os.path.join(self._dir, name)
            try:
                created = datetime.strptime(
                    m.group(1) + "_" + m.group(2), "%Y%m%d_%H%M%S")
            except ValueError:
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            summary = {}
            try:
                with zipfile.ZipFile(path) as zf:
                    if "manifest.json" in zf.namelist():
                        manifest = json.loads(zf.read("manifest.json"))
                        if isinstance(manifest, dict):
                            summary = manifest.get("summary", {}) or {}
            except Exception:
                summary = {}
            infos.append(BackupInfo(name, path, created, m.group(4),
                                    size, summary))
        return infos

    # ----------------------------------------------------------- preview
    def preview(self, path):
        """Validate a backup ZIP and return its manifest. Raises ValueError
        on anything unexpected (bad zip, missing/undecodable state, missing
        referenced stored files)."""
        try:
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
                if "system_state.json" not in names:
                    raise ValueError(
                        "not a Command Center backup (no system_state.json)")
                state = json.loads(zf.read("system_state.json"))
                if not isinstance(state, dict):
                    raise ValueError("backup state is not a JSON object")
                manifest = {}
                if "manifest.json" in names:
                    raw = json.loads(zf.read("manifest.json"))
                    if isinstance(raw, dict):
                        manifest = raw
                manifest.setdefault("files", [])
                manifest.setdefault("data_files", [])
                for entry in manifest["files"] + manifest["data_files"]:
                    if entry.get("stored") not in names:
                        raise ValueError(
                            f"backup is incomplete (missing "
                            f"{entry.get('stored')!r})")
                return manifest
        except zipfile.BadZipFile as exc:
            raise ValueError(f"corrupt ZIP: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"corrupt JSON in backup: {exc}") from exc

    # ------------------------------------------------------------ restore
    def restore(self, path, restore_files=True):
        """Validate + restore. Reloads the broker from the snapshot (so all
        tabs redraw via load_state) and, when restore_files, writes the
        referenced files back to their recorded locations."""
        manifest = self.preview(path)
        with zipfile.ZipFile(path) as zf:
            state = json.loads(zf.read("system_state.json"))
            if not isinstance(state, dict):
                raise ValueError("backup state is not a JSON object")
            if restore_files:
                for entry in manifest["files"]:
                    src = entry.get("src")
                    if not src or not os.path.isabs(src):
                        continue
                    try:
                        payload = zf.read(entry["stored"])
                        os.makedirs(os.path.dirname(src), exist_ok=True)
                        with open(src, "wb") as fh:
                            fh.write(payload)
                    except (OSError, KeyError) as exc:
                        manifest.setdefault("_warnings", []).append(
                            f"{src}: {exc}")
                data_dir = os.path.join(os.path.dirname(self._dir), "data")
                for entry in manifest["data_files"]:
                    stored = entry.get("stored", "")
                    if not stored.startswith("data/"):
                        continue
                    try:
                        payload = zf.read(stored)
                        os.makedirs(data_dir, exist_ok=True)
                        with open(os.path.join(data_dir,
                                               os.path.basename(stored)),
                                  "wb") as fh:
                            fh.write(payload)
                    except (OSError, KeyError) as exc:
                        manifest.setdefault("_warnings", []).append(
                            f"{stored}: {exc}")
        if self.broker is not None:
            self.broker.load_state(state)
        manifest["files_restored"] = len(manifest["files"])
        manifest["data_files_restored"] = len(manifest["data_files"])
        return manifest

    # ------------------------------------------------------------ rotate
    def rotate(self):
        """Delete the oldest backups beyond `self.keep`; returns removed."""
        backups = self.list()
        keep = self.keep or 20
        removed = []
        for info in backups[keep:]:
            try:
                os.remove(info.path)
                removed.append(info.path)
            except OSError:
                pass
        return removed
