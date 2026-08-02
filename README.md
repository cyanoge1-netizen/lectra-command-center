# Lectra - Academic & Life Command Center (Beta 0.5)

An all-in-one, fully local student dashboard built with Python and PyQt6:
academics, attendance, syllabus tracking, marks & trends, habits, tasks, and
predictive insights — no account, no internet, no API keys.

---

## ✨ Features (9 tabs)

- **Today Brief** — one screen for today: classes, homework, assignments,
  exams/deadlines, habits, and a checklist task column.
- **Home Cockpit** — at-a-glance cards, quick-add header, live unstudied-topic
  warnings, and sidebar badges.
- **Profiles** — student profile with photo and instructor registry.
- **Syllabus Engine & Subject Hub** — per-subject topic trees with study
  priority + progress bars; exam framework.
- **Attendance** — class routine, daily logging, attendance <75% warnings, and
  risk predictions.
- **Life & Daily Goals** — daily goals, habit streaks, weekly study minutes.
- **Materials** — course materials with video/audio download backend (yt-dlp).
- **Marks & Trends** — per-subject marks with trend plots (pyqtgraph).
- **Checklist (Phase 11)** — collapsible subject cards with topic checkboxes
  (writes syllabus status directly), custom tasks CRUD, a 13-week Sunday-start
  heatmap, and a streak counter.
- **Predictive Engine** — fully local ML (BayesianRidge / RandomForest on
  bundled CSVs): grade deflection, focus windows, habit cascade.
- **Backup & Restore** — self-contained ZIP backups (state + referenced files +
  manifest), keep-N rotation, auto-daily backup, one-click restore.

---

## 🚀 Run

```bash
pip install -r requirements.txt
python3 main_gui.py
```

> `yt-dlp` (optional) powers video/audio downloads in the Materials tab; the
> app runs without it.

---

## 📦 Packaging

Release zips (`lectra_beta_0.5.zip`) are produced clean: all source modules,
`data/` seed files, and `system_state.json` (the app's state schema) — with
`__pycache__/` and `backups/` excluded. Restore a backup via the Backup &
Restore dialog to repopulate any environment.
