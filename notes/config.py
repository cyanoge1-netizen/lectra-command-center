# -*- coding: utf-8 -*-
"""Notes module paths (ported from the ERP project, adapted to this repo)."""
import os

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

EXPORTS_DIR = os.path.join(ROOT_DIR, "Exports")
CHARTS_DIR = os.path.join(EXPORTS_DIR, "Charts")
NOTES_DIR = os.path.join(EXPORTS_DIR, "Notes_PDF")
CSV_BACKUPS_DIR = os.path.join(EXPORTS_DIR, "CSV_Backups")

TEMPLATES_DIR = os.path.join(ROOT_DIR, "assets", "templates")
PROFILE_PHOTOS_DIR = os.path.join(ROOT_DIR, "data", "profile_photos")
SESSION_FILE = os.path.join(ROOT_DIR, "data", "session.token")

for _d in (CHARTS_DIR, NOTES_DIR, CSV_BACKUPS_DIR, TEMPLATES_DIR,
           PROFILE_PHOTOS_DIR):
    os.makedirs(_d, exist_ok=True)
