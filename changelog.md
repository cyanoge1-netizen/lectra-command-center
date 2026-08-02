# Changelog

## [Beta 0.5] - 2026-08-02
### Added
- Branded **Lectra** and re-versioned to **Beta 0.5** (window title + README).
- `README.md`, `changelog.md`, and `requirements.txt` for the project.

### Changed
- Release `lectra_beta_0.5.zip` packages the full app clean: source modules,
  `data/` seeds, and `system_state.json` (no `__pycache__`, no `backups/`).

### Already included (Phases 1–11, built 2026-08-01/02)
- **P1 Today Brief**: classes, homework, assignments, exams/deadlines, habits,
  and a checklist task column synced to the checklist section.
- **P2 Marks & Trends**: per-subject marks with trend plots.
- **P3 Syllabus Checklist**: subject cards w/ topic checkboxes (single source
  of truth for syllabus status), custom tasks CRUD, 13-week heatmap, streak.
- **Backup & Restore**: ZIP backups w/ manifest, keep-N rotation, auto-daily +
  auto-close backups, `DataBroker.load_state` deep-restore across all tabs.
- **English-digit fix**: `QLocale.setDefault(en_US)` before QApplication so
  numeric widgets render `0-9` even under a Bengali OS locale.

## [Phase 1 Foundation] - 2026-08-01
- `databroker.py` centralized state store (atomic JSON persistence,
  per-section signals), global QSS skin (`styles.py`), 9-tab skeleton,
  predictive engine (grade deflection, focus windows, habit cascade), system
  locale/session stamping.
