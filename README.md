# Lectra - Academic & Life Command Center (Beta 0.5)

An all-in-one, fully local student dashboard built with Python and PyQt6:
academics, attendance, syllabus tracking, marks & trends, habits, tasks,
predictive insights, and an AI note studio — no account, no internet, no
API keys required.

---

## ✨ Features (10 tabs)

- **Today Brief** — one screen for today: classes, homework, assignments,
  exams/deadlines, habits, and a checklist task column.
- **Home Cockpit** — at-a-glance cards, quick-add header, live unstudied-topic
  warnings, and sidebar badges.
- **Profiles** — student profile (auto-saves as you type) with photo and
  instructor registry.
- **Syllabus Engine & Subject Hub** — per-subject topic trees with study
  priority + progress bars; exam framework.
- **Attendance** — class routine, daily logging, attendance <75% warnings, and
  risk predictions.
- **Life & Daily Goals** — daily goals, habit streaks, weekly study minutes.
- **Materials** — course materials with video/audio download backend (yt-dlp).
- **Marks & Trends** — per-subject marks with trend plots (pyqtgraph).
- **Checklist** — collapsible subject cards with topic checkboxes (writes
  syllabus status directly), custom tasks CRUD, a 13-week Sunday-start
  heatmap, and a streak counter.
- **Notes (AI Studio)** — turn lecture files / photos / pasted text into
  polished XeLaTeX PDFs: offline markdown→LaTeX or optional AI providers
  (DeepSeek/OpenAI/Anthropic/Ollama), Tesseract OCR for images & scanned
  PDFs, offline MarianMT translation, and a per-subject **Vault** of portable
  note bundles (PDF, source.tex, meta.json, transcript.txt).
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

> Optional extras: `yt-dlp` (Materials downloads), `pytesseract` + `Pillow`
> (OCR), `transformers` + `torch` (offline translation). The app runs without
> them and hides/degrades gracefully. OCR also needs the `tesseract-ocr`
> binary: `sudo apt install tesseract-ocr`. Notes compile with XeLaTeX
> (`sudo apt install texlive-xetex`).

---

## 🧪 Tests

Stdlib `unittest` (no pytest needed):

```bash
python3 -m unittest discover -s tests -v
```

Covers `backup_manager` (create/list/preview/restore, rotation, corrupt-zip
rejection, file round-trip) and `predictive_engine` (deterministic training,
alert thresholds, habit cascade, no-fabrication guard).


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
  --hidden-import syllabus_checklist_tab --hidden-import notes_tab \
  --hidden-import backup_dialog --hidden-import backup_manager \
  --hidden-import databroker --hidden-import predictive_engine \
  --hidden-import styles --hidden-import media_backend \
  --hidden-import notes.ai_notes_pipeline --hidden-import notes.vault \
  --hidden-import notes.ai_client --hidden-import notes.settings \
  --hidden-import notes.xelatex_compiler --hidden-import notes.ocr_engine \
  --hidden-import notes.offline_translator \
  --add-data "data:data" --add-data "assets/templates:assets/templates" \
  main_gui.py
```

The executable lands at `dist/lectra` (`lectra.exe` on Windows).

