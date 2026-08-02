# -*- coding: utf-8 -*-
"""The Notes Vault: a structured, self-indexed home for generated lecture
PDFs. Layout:

  Exports/Vault/user_1/
    index.json                       <- all metadata (single source of truth)
    <Subject>/                       <- one folder per subject
       01_2026-08-02/pdf, source.tex, meta.json, transcript.txt, fonts/, assets/

index.json carries enough metadata to rebuild the folder view without
re-scanning. Ported from the ERP project; the only change is that paths
resolve through notes.config (this app is single-user, so user_id is
kept for API compatibility but defaults to 1).
"""
import json
import os
import re
from datetime import date, datetime

from notes.config import EXPORTS_DIR

INDEX_NAME = "index.json"


def sanitize_part(name: str) -> str:
    """Makes a subject/course code safe for use as a file/folder name."""
    if not name:
        return "Untitled"
    cleaned = re.sub(r"[^A-Za-z0-9 _\-]", "", name).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned or "Untitled"


class VaultEngine:
    def __init__(self, user_id: int = 1):
        self.user_id = user_id
        self.root = os.path.join(EXPORTS_DIR, "Vault", f"user_{user_id}")
        os.makedirs(self.root, exist_ok=True)
        self.index_path = os.path.join(self.root, INDEX_NAME)
        self._index = None

    # ── index helpers ──
    def _load_index(self) -> dict:
        if self._index is not None:
            return self._index
        if os.path.exists(self.index_path):
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    self._index = json.load(f)
                return self._index
            except (json.JSONDecodeError, OSError):
                pass
        self._index = {"entries": []}
        return self._index

    def _save_index(self):
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.index_path)

    # ── paths ──
    def subject_dir(self, subject: str) -> str:
        folder = os.path.join(self.root, sanitize_part(subject))
        os.makedirs(folder, exist_ok=True)
        return folder

    def build_filename(self, subject: str, lecture_index: int, title: str, ext: str) -> str:
        date_str = date.today().strftime("%Y-%m-%d")
        base = f"{sanitize_part(subject)}_{lecture_index:02d}_{date_str}"
        if title:
            clean_title = sanitize_part(title)[:40]
            if clean_title and clean_title != "Untitled":
                base += f"_{clean_title}"
        return f"{base}.{ext}"

    def bundle_dir(self, subject: str, lecture_index: int) -> str:
        """Per-note bundle folder: <Subject>/<LectureIndex>_<Date>/."""
        base = f"{int(lecture_index):02d}_{date.today().strftime('%Y-%m-%d')}"
        folder = os.path.join(self.subject_dir(subject), base)
        n = 2
        while os.path.exists(folder) and os.listdir(folder):
            folder = os.path.join(self.subject_dir(subject), f"{base}_{n}")
            n += 1
        os.makedirs(folder, exist_ok=True)
        return folder

    # ── lecture index ──
    def next_index(self, subject: str) -> int:
        highest = 0
        for e in self._load_index()["entries"]:
            if e.get("subject", "").strip().lower() == (subject or "").strip().lower():
                try:
                    highest = max(highest, int(e.get("lecture_index", 0)))
                except (TypeError, ValueError):
                    pass
        return highest + 1

    # ── CRUD ──
    def add_entry(self, subject: str, lecture_index: int, title: str,
                  pdf_path: str, tex_path: str, pages: int = 0,
                  folder: str = "", template: str = "", language: str = "",
                  options: dict = None, input_files: list = None,
                  transcript_path: str = "", fonts_dir: str = "",
                  assets_dir: str = "") -> dict:
        entry = {
            "id": self._next_id(),
            "subject": subject,
            "lecture_index": lecture_index,
            "title": title or "",
            "date": date.today().strftime("%Y-%m-%d"),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "pdf_path": pdf_path,
            "tex_path": tex_path,
            "pages": int(pages),
            "folder": folder,
            "template": template,
            "language": language,
            "options": dict(options or {}),
            "input_files": list(input_files or []),
            "transcript_path": transcript_path,
            "fonts_dir": fonts_dir,
            "assets_dir": assets_dir,
        }
        index = self._load_index()
        index["entries"].append(entry)
        self._save_index()
        return entry

    def _next_id(self) -> int:
        ids = [int(e.get("id", 0)) for e in self._load_index()["entries"]]
        return (max(ids) + 1) if ids else 1

    def entries(self, subject: str = None) -> list:
        entries = list(self._load_index()["entries"])
        if subject:
            wanted = subject.strip().lower()
            entries = [e for e in entries if e.get("subject", "").strip().lower() == wanted]
        return sorted(entries, key=lambda e: (e.get("subject", "").lower(),
                                              int(e.get("lecture_index", 0) or 0)))

    def subjects(self) -> list:
        seen = {}
        for e in self._load_index()["entries"]:
            seen.setdefault(e.get("subject", "Unknown"), e.get("subject", "Unknown"))
        return sorted(seen.keys())

    def get_entry(self, entry_id) -> dict:
        for e in self._load_index()["entries"]:
            if e.get("id") == entry_id:
                return e
        return None

    def remove_entry(self, entry_id) -> None:
        index = self._load_index()
        index["entries"] = [e for e in index["entries"] if e.get("id") != entry_id]
        self._save_index()

    def refresh(self):
        self._index = None
