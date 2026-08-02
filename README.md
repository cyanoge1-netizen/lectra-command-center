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

## 📦 Packaging & Building

### Option A — Release zip (fast, no extra deps)
Rebuild `lectra_beta_0.5.zip` from source: all source modules, `data/` seed
files, and `system_state.json`, excluding `__pycache__/` and `backups/`:

```bash
# from the project root
zip -r ../lectra_beta_0.5.zip . -x "*__pycache__*" -x "backups/*" -x ".git/*"
```

### Option B — Standalone executable (PyInstaller)
Build a one-file desktop executable. This pulls the full dependency graph
(PyQt6 + scikit-learn + pyqtgraph), so install may take a while and the build
produces a large binary (~120–250 MB):

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name lectra \
  --hidden-import today_brief_tab --hidden-import home_cockpit \
  --hidden-import profiles_tab --hidden-import syllabus_tab \
  --hidden-import attendance_tab --hidden-import life_tab \
  --hidden-import materials_tab --hidden-import marks_trends_tab \
  --hidden-import syllabus_checklist_tab --hidden-import backup_dialog \
  --hidden-import backup_manager --hidden-import databroker \
  --hidden-import predictive_engine --hidden-import styles \
  --hidden-import media_backend --add-data "data:data" main_gui.py
```

The executable lands at `dist/lectra` (`lectra.exe` on Windows).

