# Changelog

## [Beta 0.6] - 2026-08-02 (cont. 1)
### Added
- **Phase C — Decision layer**: new `decision_engine.py` ranks "what to do
  next" from the live state graph (deadline proximity, exam countdown +
  high-yield topic backlog + attendance risk per course, recovery-class
  targets, and a spaced-repetition revision queue driven by the checklist
  log's last-reviewed dates).
- Today Brief gains a **Do this next** card (top-5 scored actions with
  reasons) and a revision-queue line; Home Cockpit shows the single top
  suggestion above its Predictive Intelligence panel.
- `tests/test_decision_engine.py` (14 cases: ranking, recovery math,
  exam matching, determinism).

## [Beta 0.5] - 2026-08-02 (cont. 2)
### Added
- **Phase 12 — Notes (AI Studio)** ported from the ERP project into a new
  Notes tab: `notes/` package (pipeline, vault, AI client, settings, XeLaTeX
  compiler, OCR, offline MarianMT translator) + `notes_tab.py` GUI with
  threaded generation and a per-subject Vault browser.
- Bundled `assets/templates/` (ai_notes.tex, lecture_note.tex,
  lectro_note template, tikz_standalone.tex).

### Changed
- Graph integrity (Phase A): shared `ui_helpers.py` course-code combo +
  `confirm_course_known` guard across routine/homework/exams/task dialogs;
  codes normalized to uppercase.
- Profiles auto-save on focus-out ("saved ✓" flash); `Ctrl+1..9` tab
  shortcuts (`Ctrl+0` for the last tab), `Ctrl+N` quick-adds homework;
  app always opens on Today Brief.
- `requirements.txt` documents optional OCR/translation deps; `.gitignore`
  now excludes `Exports/` and `data/settings_*.json` (API keys).

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

## [Beta 0.6] - 2026-08-02 (cont. 2)
### Added
- **Real syllabus dataset**: `data/syllabus.json` extracted from the SEC CSE
  UG curriculum PDF (`~/Downloads/syllabus.pdf`, 2025-26) — 8 semesters, 98
  courses, 423 topics. One-off parser (pymupdf) matched semester tables to
  each `Course Contents:` outline, pulling theory/lab hours, credits and
  yield-ranked topic lists; Project/Viva/Thesis courses get clean fallback
  topics. Import via Syllabus Engine → Import syllabus JSON (merges into
  existing semesters).

## [Beta 0.6] - 2026-08-02 (cont. 3)
### Fixed
- **Syllabus Engine drawer is now dismissible**: added a `✕` close button in
  the course-details panel header (`_close_drawer` clears the table selection
  so the panel collapses). Previously there was no way to close it.

## [Beta 0.6] - 2026-08-02 (cont. 4)
### Fixed
- **Precise semester week**: Today Brief now shows the exact week — e.g.
  `WEEK 4 OF SEMESTER · day 1 of 7` — and no longer fakes "WEEK 1" when the
  semester start date is still in the future (it now reads "Semester starts
  in N days"). The set-start dialog also pins the date format to `yyyy-MM-dd`
  so the chosen date is unambiguous.

## [Beta 0.6] - 2026-08-02 (cont. 5)
### Added
- **Off-day awareness**: Today Brief now treats weekends (days beyond
  `attendance.days_per_week`, default 5 = Sun–Thu) and listed holidays as
  days off — showing "🎉 Today is off — relax" instead of the semester week,
  and clearing the routine with "🎉 Day off — no classes, relax". A
  **Holiday today** toggle in the routine card marks/unmarks the current date
  in `attendance.holidays`.

## [Phase 1 Foundation] - 2026-08-01
- `databroker.py` centralized state store (atomic JSON persistence,
  per-section signals), global QSS skin (`styles.py`), 9-tab skeleton,
  predictive engine (grade deflection, focus windows, habit cascade), system
  locale/session stamping.
