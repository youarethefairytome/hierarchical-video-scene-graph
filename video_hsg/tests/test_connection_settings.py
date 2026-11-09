"""连接设置持久化、重启恢复、留空保留 Key 和失败原子性。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from video_hsg.connection_settings import FIELDS, load_connection_environment, save_connection_environment


class ConnectionSettingsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.environment = patch.dict(os.environ)
        self.environment.start()
        for name in FIELDS:
            os.environ.pop(name, None)

    def tearDown(self):
        self.environment.stop()
        self.folder.cleanup()

    def test_save_and_restart_load_without_interpolation(self):
        path = self.root / ".env"
        path.write_text("# keep comments\nOTHER_SETTING=unchanged\n", encoding="utf-8")
        secret = "test-$literal-${UNSET}-'quoted'-\\slash-\"double\""
        save_connection_environment(self.root, "https://fixture.invalid/v1", secret, "model-a")
        self.assertEqual(os.environ["VIDEO_LLM_API_KEY"], secret)
        self.assertEqual(dotenv_values(path, interpolate=False)["VIDEO_LLM_API_KEY"], secret)
        self.assertIn("# keep comments", path.read_text(encoding="utf-8"))
        for name in FIELDS:
            os.environ.pop(name, None)
        load_connection_environment(self.root)
        self.assertEqual(os.environ["VIDEO_LLM_API_KEY"], secret)
        self.assertEqual(os.environ["VIDEO_LLM_BASE_URL"], "https://fixture.invalid/v1")
        self.assertEqual(os.environ["VIDEO_LLM_MODEL"], "model-a")
        self.assertNotIn("OTHER_SETTING", os.environ)

    def test_blank_key_preserves_stored_key_and_updates_model(self):
        save_connection_environment(self.root, "https://fixture.invalid/v1", "first-key", "model-a")
        os.environ["VIDEO_LLM_API_KEY"] = "old-shell-key"
        save_connection_environment(self.root, "https://fixture.invalid/v1", "  ", "model-b")
        self.assertEqual(os.environ["VIDEO_LLM_API_KEY"], "first-key")
        self.assertEqual(os.environ["VIDEO_LLM_MODEL"], "model-b")
        self.assertEqual(len(list(self.root.glob('.env.*'))), 0)

    def test_invalid_settings_do_not_modify_saved_configuration(self):
        save_connection_environment(self.root, "https://fixture.invalid/v1", "first-key", "model-a")
        before = (self.root / ".env").read_bytes()
        for endpoint, key in (("", "new-key"), ("https://fixture.invalid?key=secret", "key"),
                              ("https://fixture.invalid", "bad\nkey")):
            with self.assertRaises(ValueError):
                save_connection_environment(self.root, endpoint, key, "changed-model")
            self.assertEqual((self.root / ".env").read_bytes(), before)
            self.assertEqual(os.environ["VIDEO_LLM_MODEL"], "model-a")

    def test_failed_write_does_not_update_process_environment(self):
        save_connection_environment(self.root, "https://fixture.invalid/v1", "first-key", "model-a")
        before = (self.root / ".env").read_bytes()
        with patch("video_hsg.connection_settings.os.replace", side_effect=PermissionError()):
            with self.assertRaises(OSError):
                save_connection_environment(self.root, "https://other.invalid/v1", "new-key", "model-b")
        self.assertEqual((self.root / ".env").read_bytes(), before)
        self.assertEqual(os.environ["VIDEO_LLM_API_KEY"], "first-key")
        self.assertEqual(list(self.root.glob('.env.*')), [])


if __name__ == "__main__":
    unittest.main()
