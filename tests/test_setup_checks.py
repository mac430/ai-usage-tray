import os, tempfile, time, unittest
from pathlib import Path
from unittest import mock

from aiusage import setup_checks as sc
from aiusage.model import ProviderStatus, UsageWindow


class T(unittest.TestCase):
    def test_describe(self):
        ok = ProviderStatus("gemini", "ok", "", "plus", [UsageWindow("session", "目前用量", 59, None, "")], None)
        self.assertEqual(sc.describe(ok)[0], True); self.assertIn("59", sc.describe(ok)[1])
        self.assertFalse(sc.describe(ProviderStatus("gemini", "login_required", "", fetched_at=None))[0])
        self.assertIn("parse_error", sc.describe(ProviderStatus("gemini", "parse_error", "x"))[1])

    def test_pause(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("aiusage.setup_checks.pause_file", lambda k: Path(d) / f"p-{k}"), \
                mock.patch("aiusage.setup_checks.BASE_DIR", Path(d)):
            self.assertFalse(sc.is_paused("g"))
            sc.set_pause("g", True); self.assertTrue(sc.is_paused("g"))
            self.assertFalse(sc.is_paused("g", now=time.time() + 3600))   # 過期忽略
            sc.set_pause("g", False); self.assertFalse(sc.is_paused("g"))

    def test_claude_login(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(sc.claude_login_exists(Path(d)))
            (Path(d) / ".claude").mkdir(); (Path(d) / ".claude" / ".credentials.json").write_text("{}")
            self.assertTrue(sc.claude_login_exists(Path(d)))


if __name__ == "__main__":
    unittest.main()
