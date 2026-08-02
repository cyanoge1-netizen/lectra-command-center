# Tests for backup_manager.py (stdlib unittest — no pytest needed).
#
# Run:  python3 -m unittest discover -s tests -v
import json
import os
import shutil
import tempfile
import unittest
import zipfile

from databroker import DataBroker
from backup_manager import BackupManager, snapshot_summary


def _make_broker_and_manager(tmp, keep=3):
    state_dir = os.path.join(tmp, "state")
    os.makedirs(state_dir, exist_ok=True)
    broker = DataBroker(state_path=os.path.join(state_dir, "system_state.json"))
    manager = BackupManager(
        broker=broker,
        backups_dir=os.path.join(tmp, "backups"),
        keep=keep,
    )
    return broker, manager


class BackupManagerTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cc_test_backup_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.broker, self.manager = _make_broker_and_manager(self._tmp)

    def test_create_writes_valid_zip_with_manifest(self):
        path = self.manager.create(reason="manual")
        self.assertTrue(os.path.isfile(path), "backup zip should exist")
        self.assertTrue(os.path.basename(path).startswith("backup_"))
        self.assertTrue(path.endswith(".zip"))
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            self.assertIn("system_state.json", names)
            self.assertIn("manifest.json", names)
            manifest = json.loads(zf.read("manifest.json"))
            self.assertEqual(manifest["reason"], "manual")
            self.assertIn("summary", manifest)
            self.assertIn("data_files", manifest)
        # broker's last_backup metadata was updated
        self.assertIsNotNone(self.broker.get("backup.last_backup"))
        self.assertEqual(self.broker.get("backup.last_backup_reason"), "manual")

    def test_list_returns_newest_first(self):
        for reason in ("first", "second", "third"):
            self.manager.create(reason=reason)
        infos = self.manager.list()
        self.assertEqual(len(infos), 3)
        # newest first
        for a, b in zip(infos, infos[1:]):
            self.assertGreaterEqual(a.created, b.created)

    def test_rotation_keeps_newest_n(self):
        for i in range(6):  # 6 backups, keep=3
            self.manager.create(reason=f"r{i}")
        infos = self.manager.list()
        self.assertEqual(len(infos), 3, "rotation should keep only the newest 3")

    def test_preview_accepts_valid_backup(self):
        path = self.manager.create(reason="manual")
        manifest = self.manager.preview(path)
        self.assertEqual(manifest["reason"], "manual")
        self.assertIn("summary", manifest)

    def test_preview_rejects_non_zip(self):
        path = os.path.join(self._tmp, "backups", "not_a_zip.txt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("this is not a zip file")
        with self.assertRaises(ValueError):
            self.manager.preview(path)

    def test_preview_rejects_zip_without_state(self):
        path = os.path.join(self._tmp, "backups", "fake_backup.zip")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("random.txt", "hello")
        with self.assertRaises(ValueError):
            self.manager.preview(path)

    def test_preview_rejects_corrupt_json_state(self):
        path = os.path.join(self._tmp, "backups", "corrupt_state.zip")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("system_state.json", "{not valid json")
        with self.assertRaises(ValueError):
            self.manager.preview(path)

    def test_restore_round_trip_reloads_broker(self):
        self.broker.set("profile.student.full_name", "Original Name")
        path = self.manager.create(reason="manual")
        # mutate after the backup
        self.broker.set("profile.student.full_name", "Changed Name")
        self.broker.set("syllabus.exams", ["E1", "E2"])
        # restore -> broker should reflect the backed-up snapshot
        manifest = self.manager.restore(path)
        self.assertEqual(self.broker.get("profile.student.full_name"),
                         "Original Name")
        self.assertEqual(self.broker.get("syllabus.exams"), [])

    def test_backup_includes_referenced_files_and_restores_them(self):
        photo = os.path.join(self._tmp, "refs", "photo.jpg")
        os.makedirs(os.path.dirname(photo), exist_ok=True)
        with open(photo, "wb") as fh:
            fh.write(b"\xff\xd8 fake jpeg payload")
        self.broker.set("profile.student.photo_path", photo)
        path = self.manager.create(reason="manual")

        with zipfile.ZipFile(path) as zf:
            stored = [n for n in zf.namelist() if n.startswith("files/")]
            self.assertEqual(len(stored), 1)
            self.assertEqual(zf.read(stored[0]), b"\xff\xd8 fake jpeg payload")

        # delete the file, then restore it
        os.remove(photo)
        self.manager.restore(path)
        self.assertTrue(os.path.isfile(photo), "referenced file should be restored")
        with open(photo, "rb") as fh:
            self.assertEqual(fh.read(), b"\xff\xd8 fake jpeg payload")

    def test_snapshot_summary_counts(self):
        self.broker.set("syllabus.semesters.sem1.CSE101.topics",
                        [{"name": "T1", "status": "Pending"},
                         {"name": "T2", "status": "Completed"}])
        self.broker.set("homework", ["h1", "h2"])
        summary = snapshot_summary(self.broker.snapshot())
        self.assertEqual(summary["semesters"], 1)
        self.assertEqual(summary["courses"], 1)
        self.assertEqual(summary["topics"], 2)
        self.assertEqual(summary["homework"], 2)


if __name__ == "__main__":
    unittest.main()
