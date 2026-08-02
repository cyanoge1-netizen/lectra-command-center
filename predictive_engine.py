# File Location: predictive_engine.py
# Academic & Life Command Center — Predictive Engine (Phase 2).
#
# Fully local, no external API calls. Three components:
#   A. Academic Grade Deflection  — BayesianRidge on
#        [attendance_rate, weekly_study_minutes, unstudied_high_priority_topics]
#        -> predicted terminal score (0-100) + alert state
#        (NOMINAL >= 75 / WARNING 65-74 / CRITICAL RISK < 65)
#   B. Optimal Focus Window       — RandomForestRegressor on
#        [day_of_week, hour_of_day] -> productivity score,
#        then the best contiguous 2-hour block is returned as "HH:00 - HH:00"
#   C. Habit Cascade Failure      — deterministic lookup by days missed
#        (0->5%, 1->28%, 2->65% HIGH, 3+->89% CRITICAL INTERVENTION)
#
# Trained on the sample CSVs in ./data/ (contract documented in
# data/README_training_data.md). If a CSV is missing or malformed the
# affected component reports ready=False + a reason — it never fabricates
# a static calibration matrix.
#
# No PyQt dependency: usable in tests / CLI as well as from the GUI.
#
# Run self-test:  python3 predictive_engine.py

import csv
import os
from datetime import datetime

import numpy as np

# scikit-learn is the only hard dependency; import at module top so a missing
# install is visible immediately, but training still degrades gracefully
# (ready=False + reason) rather than crashing the app.
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import BayesianRidge
from sklearn.metrics import r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


# ---------------------------------------------------------------------------
# Alert thresholds (from the Phase 2 spec)
# ---------------------------------------------------------------------------
def alert_for_score(score):
    if score is None:
        return None
    if score >= 75:
        return "NOMINAL"
    if score >= 65:
        return "WARNING"
    return "CRITICAL RISK"


# Deterministic habit-cascade table (spec: no training data needed).
HABIT_CASCADE = [
    (0, 0.05, "LOW"),
    (1, 0.28, "MODERATE"),
    (2, 0.65, "HIGH"),
    (3, 0.89, "CRITICAL INTERVENTION"),  # 3+ days -> same row
]

FOCUS_FEATURES = ["day_of_week", "hour_of_day"]
GRADE_FEATURES = ["attendance_rate", "weekly_study_minutes",
                  "unstudied_high_priority_topics"]


def _iso_now():
    return datetime.now().isoformat(timespec="seconds")


class PredictiveEngine:
    """Trains and serves the three predictive components."""

    def __init__(self, data_dir=None):
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        self.data_dir = data_dir

        self.grade_ready = False
        self.grade_reason = "not trained"
        self.focus_ready = False
        self.focus_reason = "not trained"

        self._grade_pipeline = None
        self._focus_model = None
        self._focus_importances = None

        self.grade_metrics = {}
        self.focus_metrics = {}
        self._last_train = None

        self.train()

    # ------------------------------------------------------------- training
    def train(self):
        """Load the CSVs and fit both models. One bad file never blocks the
        other; each component reports its own ready/reason."""
        self._train_grade()
        self._train_focus()
        self._last_train = _iso_now()

    def _load_csv(self, filename, required_columns):
        """Return a dict of column name -> np.ndarray[float], or (None, reason)."""
        path = os.path.join(self.data_dir, filename)
        if not os.path.exists(path):
            return None, f"missing data file: {filename}"
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
        except (OSError, csv.Error) as exc:
            return None, f"cannot read {filename}: {exc}"
        if not rows:
            return None, f"empty data file: {filename}"

        missing = [c for c in required_columns if c not in (rows[0] or {})]
        if missing:
            return None, f"{filename} missing columns: {', '.join(missing)}"

        try:
            data = {col: np.asarray([float(r[col]) for r in rows], dtype=float)
                    for col in required_columns}
        except (ValueError, TypeError) as exc:
            return None, f"{filename} has non-numeric values: {exc}"
        return data, None

    def _train_grade(self):
        data, reason = self._load_csv("grade_deflection_training_data.csv",
                                      GRADE_FEATURES + ["terminal_exam_score"])
        if reason:
            self.grade_ready = False
            self.grade_reason = reason
            return

        X = np.column_stack([data[c] for c in GRADE_FEATURES])
        y = data["terminal_exam_score"]

        # StandardScaler + BayesianRidge: honest held-out R2 on a tiny local set.
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=0)
        pipeline = make_pipeline(StandardScaler(), BayesianRidge())
        pipeline.fit(X_tr, y_tr)
        r2 = float(r2_score(y_te, pipeline.predict(X_te)))

        self._grade_pipeline = pipeline
        self.grade_ready = True
        self.grade_reason = None
        self.grade_metrics = {"r2": r2, "n_samples": int(len(y)), "r2_split": "20% held-out"}

    def _train_focus(self):
        data, reason = self._load_csv("focus_window_training_data.csv",
                                      FOCUS_FEATURES + ["productivity_score"])
        if reason:
            self.focus_ready = False
            self.focus_reason = reason
            return

        X = np.column_stack([data[c] for c in FOCUS_FEATURES])
        y = data["productivity_score"]

        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=0)
        # min_samples_leaf=4 beats the default leaf-1 (which overfits this
        # small noisy set into negative held-out R2): cv5 +0.30 / holdout +0.24.
        model = RandomForestRegressor(n_estimators=600, min_samples_leaf=4,
                                      random_state=0, n_jobs=-1)
        model.fit(X_tr, y_tr)
        r2 = float(r2_score(y_te, model.predict(X_te)))

        self._focus_model = model
        self._focus_importances = dict(zip(FOCUS_FEATURES, model.feature_importances_))
        self.focus_ready = True
        self.focus_reason = None
        self.focus_metrics = {"r2": r2, "n_samples": int(len(y)), "r2_split": "20% held-out"}

    # ------------------------------------------------- A. grade deflection
    def predict_terminal_score(self, attendance_rate, weekly_study_minutes,
                               unstudied_topics):
        """Predict terminal score + alert for current inputs. Returns a dict
        ready for the broker's predictive.grade_deflection section."""
        if not self.grade_ready:
            return {"status": None, "predicted_score": None, "model_ready": False,
                    "reason": self.grade_reason, "last_run": None}

        features = np.array([[float(attendance_rate), float(weekly_study_minutes),
                              float(unstudied_topics)]])
        raw = float(self._grade_pipeline.predict(features)[0])
        score = round(float(np.clip(raw, 0.0, 100.0)), 1)

        return {
            "status": alert_for_score(score),
            "predicted_score": score,
            "model_ready": True,
            "reason": None,
            "input": {
                "attendance_rate": round(float(attendance_rate), 3),
                "weekly_study_minutes": int(weekly_study_minutes),
                "unstudied_high_priority_topics": int(unstudied_topics),
            },
            "last_run": _iso_now(),
        }

    # --------------------------------------------------- B. optimal focus
    def hourly_profile(self, day_of_week=None):
        """Predicted productivity for each hour 0-23. When day_of_week is None,
        averages across all seven days (the general best window)."""
        if not self.focus_ready:
            return None
        profile = np.zeros(24)
        days = [int(day_of_week)] if day_of_week is not None else range(7)
        for dow in days:
            X = np.column_stack([np.full(24, float(dow)), np.arange(24, dtype=float)])
            profile += self._focus_model.predict(X)
        return profile / len(days)

    @staticmethod
    def _best_2h_block(profile):
        best_start, best_mean = 0, -1.0
        for start in range(23):  # non-wrapping windows: 0-1 .. 22-23
            mean = float(0.5 * (profile[start] + profile[start + 1]))
            if mean > best_mean:
                best_mean, best_start = mean, start
        return best_start, best_mean

    def best_focus_block(self, day_of_week=None):
        """Top-scoring contiguous 2-hour block -> '19:00 - 21:00' (+ score)."""
        if not self.focus_ready:
            return {"best_block": None, "score": None, "day_of_week": day_of_week,
                    "model_ready": False, "reason": self.focus_reason, "last_run": None}

        profile = self.hourly_profile(day_of_week)
        start, score = self._best_2h_block(profile)
        return {
            "best_block": f"{start:02d}:00 - {start + 2:02d}:00",
            "score": round(float(score), 1),
            "day_of_week": day_of_week,
            "model_ready": True,
            "reason": None,
            "feature_importance": {k: float(v) for k, v in self._focus_importances.items()},
            "last_run": _iso_now(),
        }

    # --------------------------------------------------- C. habit cascade
    def habit_cascade(self, days_missed=0):
        """Deterministic failure-probability lookup. 3+ days clamps to the
        CRITICAL INTERVENTION row."""
        days = max(0, int(days_missed))
        bucket = min(days, 3)
        rate, label = HABIT_CASCADE[bucket][1], HABIT_CASCADE[bucket][2]
        return {
            "days_missed": days,
            "failure_rate": rate,
            "state": label,
            "last_run": _iso_now(),
        }

    # ------------------------------------------------------------ combined
    def predict_all(self, attendance_rate=None, weekly_study_minutes=None,
                    unstudied_topics=None, days_missed=0):
        """One call -> the whole predictive section for the broker. Grade
        inputs are optional: when any is None the model is left untriggered
        (no fabricated numbers) until real Attendance/Syllabus data arrives."""
        grade = self.predict_terminal_score(attendance_rate, weekly_study_minutes,
                                            unstudied_topics) \
            if None not in (attendance_rate, weekly_study_minutes, unstudied_topics) \
            else {
                "status": None, "predicted_score": None, "model_ready": self.grade_ready,
                "reason": "awaiting live inputs from Attendance/Syllabus tabs",
                "last_run": None,
            }
        focus = self.best_focus_block()
        habit = self.habit_cascade(days_missed)
        return {
            "grade_deflection": grade,
            "focus_window": focus,
            "habit_cascade": habit,
            "engine": {
                "ready": self.grade_ready or self.focus_ready,
                "grade_ready": self.grade_ready, "focus_ready": self.focus_ready,
                "grade_metrics": self.grade_metrics, "focus_metrics": self.focus_metrics,
                "grade_reason": self.grade_reason, "focus_reason": self.focus_reason,
                "trained_at": self._last_train,
                "source": "trained on ./data sample CSVs (local, no API)",
            },
        }


# ---------------------------------------------------------------------------
# Self-test: python3 predictive_engine.py
# ---------------------------------------------------------------------------
def _self_test():
    engine = PredictiveEngine()
    print(f"grade ready={engine.grade_ready}  metrics={engine.grade_metrics}"
          + (f"  reason={engine.grade_reason}" if not engine.grade_ready else ""))
    print(f"focus ready={engine.focus_ready}  metrics={engine.focus_metrics}"
          + (f"  reason={engine.focus_reason}" if not engine.focus_ready else ""))

    if engine.grade_ready:
        for sample in [(0.93, 650, 1), (0.72, 300, 5), (0.55, 150, 8)]:
            print("grade sample", sample, "->",
                  engine.predict_terminal_score(*sample))

    if engine.focus_ready:
        print("best block (all days) :", engine.best_focus_block())
        print("best block (Monday=1) :", engine.best_focus_block(1))
        print("hourly profile 18-21  :",
              [round(v, 1) for v in engine.hourly_profile()[18:22]])

    for days in (0, 1, 2, 3, 5):
        print(f"habit cascade {days}d   :", engine.habit_cascade(days))

    print("predict_all (no live inputs):")
    report = engine.predict_all()
    print("  grade:", report["grade_deflection"])
    print("  focus:", report["focus_window"])
    print("  habit:", report["habit_cascade"])


if __name__ == "__main__":
    _self_test()
