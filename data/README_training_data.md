# Training Data — Predictive Engine (Phase 2)

Two synthetic-but-realistic CSVs for `predictive_engine.py`. Both were generated with a known
ground-truth relationship plus Gaussian noise, so a Bayesian Ridge / Random Forest model trained
on them will produce sane, non-arbitrary predictions instead of the model inventing numbers.

## grade_deflection_training_data.csv (180 rows)

| Column | Type | Range | Notes |
|---|---|---|---|
| `attendance_rate` | float | 0.35–1.0 | fraction of classes attended |
| `weekly_study_minutes` | int | 30–1200 | self-logged study time |
| `unstudied_high_priority_topics` | int | 0–8 | from syllabus tracker |
| `terminal_exam_score` | float | 20–100 | target variable |
| `alert_state` | str | NOMINAL / WARNING / CRITICAL RISK | derived from score thresholds (≥75 / 65–74 / <65) |

Feed `attendance_rate`, `weekly_study_minutes`, `unstudied_high_priority_topics` as `X` and
`terminal_exam_score` as `y` into `BayesianRidge()`.

## focus_window_training_data.csv (244 rows)

| Column | Type | Range | Notes |
|---|---|---|---|
| `week_number` | int | 1–10 | which logged week |
| `day_of_week` | int | 0–6 | 0=Sunday … 6=Saturday |
| `hour_of_day` | int | 6–23 | logged session start hour |
| `productivity_score` | float | 10–100 | self-rated/telemetry-derived focus score |

Feed `day_of_week`, `hour_of_day` as `X` and `productivity_score` as `y` into
`RandomForestRegressor()`. To predict "today's best window," fix `day_of_week` to today and sweep
`hour_of_day` 0–23, then pick the top-scoring contiguous 2-hour block.

## Replacing with real data later

Once your actual attendance/study-log/syllabus data exists in `databroker.py`, export it in this
same column format and retrain — the schema is the contract the ML code should be written against.
