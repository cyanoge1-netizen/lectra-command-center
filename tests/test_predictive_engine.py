# Tests for predictive_engine.py (stdlib unittest — no pytest needed).
#
# Run:  python3 -m unittest discover -s tests -v
import os
import unittest

from predictive_engine import (PredictiveEngine, alert_for_score,
                               HABIT_CASCADE)


class PredictiveEngineTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Points at the repo's data/ directory regardless of cwd.
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "data")
        cls.engine = PredictiveEngine(data_dir=data_dir)

    def test_models_train_on_bundled_data(self):
        self.assertTrue(self.engine.grade_ready,
                        self.engine.grade_reason)
        self.assertTrue(self.engine.focus_ready,
                        self.engine.focus_reason)
        self.assertIn("r2", self.engine.grade_metrics)
        self.assertIn("n_samples", self.engine.focus_metrics)

    def test_training_is_deterministic(self):
        # Same seed -> effectively identical metrics on every run. RandomForest
        # with n_jobs=-1 can reorder tree aggregation by a few ulps, so compare
        # with a tight tolerance rather than exact equality.
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "data")
        again = PredictiveEngine(data_dir=data_dir)
        self.assertAlmostEqual(self.engine.grade_metrics["r2"],
                               again.grade_metrics["r2"], places=10)
        self.assertAlmostEqual(self.engine.focus_metrics["r2"],
                               again.focus_metrics["r2"], places=10)

    def test_alert_for_score_thresholds(self):
        self.assertIsNone(alert_for_score(None))
        self.assertEqual(alert_for_score(90), "NOMINAL")
        self.assertEqual(alert_for_score(75), "NOMINAL")
        self.assertEqual(alert_for_score(74), "WARNING")
        self.assertEqual(alert_for_score(65), "WARNING")
        self.assertEqual(alert_for_score(64), "CRITICAL RISK")

    def test_habit_cascade_table(self):
        for days, rate, label in HABIT_CASCADE:
            result = self.engine.habit_cascade(days)
            self.assertEqual(result["days_missed"], days)
            self.assertEqual(result["failure_rate"], rate)
            self.assertEqual(result["state"], label)

    def test_habit_cascade_clamps_above_three(self):
        result = self.engine.habit_cascade(10)
        self.assertEqual(result["days_missed"], 10)
        self.assertEqual(result["state"], "CRITICAL INTERVENTION")
        self.assertEqual(result["failure_rate"], HABIT_CASCADE[3][1])

    def test_predict_terminal_score_clips_and_alerts(self):
        result = self.engine.predict_terminal_score(1.0, 1000, 0)
        self.assertTrue(result["model_ready"])
        score = result["predicted_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)
        self.assertEqual(result["status"], alert_for_score(score))

    def test_predict_all_without_live_inputs_does_not_fabricate(self):
        report = self.engine.predict_all()
        grade = report["grade_deflection"]
        self.assertIsNone(grade["predicted_score"])
        self.assertIsNone(grade["status"])
        self.assertTrue(grade["model_ready"])
        self.assertIn("awaiting live inputs", grade["reason"])

    def test_best_focus_block_shape(self):
        result = self.engine.best_focus_block()
        self.assertTrue(result["model_ready"])
        self.assertRegex(result["best_block"],
                         r"^\d{2}:00 - \d{2}:00$")
        self.assertIn("feature_importance", result)

    def test_hourly_profile_len(self):
        profile = self.engine.hourly_profile()
        self.assertIsNotNone(profile)
        self.assertEqual(len(profile), 24)


if __name__ == "__main__":
    unittest.main()
