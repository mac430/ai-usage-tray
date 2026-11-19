import json, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path

from aiusage.providers.codex import parse_usage, read_credentials, window_label

NOW = datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)
SAMPLE = {"plan_type": "plus", "rate_limit": {"allowed": True, "limit_reached": False,
    "primary_window": {"used_percent": 27, "limit_window_seconds": 18000, "reset_after_seconds": 3600, "reset_at": 1782770922},
    "secondary_window": {"used_percent": 4, "limit_window_seconds": 604800, "reset_after_seconds": 566340, "reset_at": 1783357722}}}


class T(unittest.TestCase):
    def test_ok(self):
        st = parse_usage(SAMPLE, NOW)
        self.assertEqual(st.status, "ok"); self.assertEqual(st.plan, "plus")
        self.assertEqual([w.label for w in st.windows], ["5 小時", "每週"])
        self.assertEqual(st.window("session").used_percent, 27)
        self.assertEqual(st.window("weekly").remaining_percent, 96)

    def test_monthly_only_and_zero(self):
        p = {"plan_type": "go", "rate_limit": {"primary_window": {"used_percent": 100, "limit_window_seconds": 2592000, "reset_after_seconds": 86400}}}
        st = parse_usage(p, NOW)
        self.assertEqual(st.status, "ok"); self.assertEqual(st.windows[0].label, "每月")
        self.assertEqual(st.windows[0].remaining_percent, 0); self.assertIsNotNone(st.windows[0].resets_at)

    def test_bad(self):
        for p in (None, [], {}, {"rate_limit": {}}, {"rate_limit": {"primary_window": {"used_percent": 150}}},
                  {"rate_limit": {"primary_window": {"used_percent": "x"}}}):
            self.assertEqual(parse_usage(p, NOW).status, "parse_error")

    def test_labels(self):
        self.assertEqual(window_label(18000), "5 小時"); self.assertEqual(window_label(None), "用量")
        self.assertEqual(window_label(604800), "每週"); self.assertEqual(window_label(2592000), "每月")

    def test_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "auth.json"
            with self.assertRaises(ValueError): read_credentials(p)
            p.write_text("{bad", encoding="utf-8")
            with self.assertRaises(ValueError): read_credentials(p)
            p.write_text(json.dumps({"OPENAI_API_KEY": "sk-x"}), encoding="utf-8")
            with self.assertRaises(ValueError): read_credentials(p)
            p.write_text(json.dumps({"tokens": {"access_token": "a", "account_id": "b"}}), encoding="utf-8")
            self.assertEqual(read_credentials(p), ("a", "b"))


if __name__ == "__main__":
    unittest.main()
