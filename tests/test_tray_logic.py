import unittest
from datetime import datetime, timedelta, timezone

from aiusage.model import ProviderStatus, UsageWindow
from aiusage.tray.logic import AlertTracker, next_interval, pick_display, tooltip

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def st(session=42, weekly=3, status="ok", fetched=NOW):
    ws = [] if status != "ok" else [
        UsageWindow("session", "目前用量", session, NOW + timedelta(hours=2), ""),
        UsageWindow("weekly", "每週上限", weekly, NOW + timedelta(days=3), ""),
    ]
    return ProviderStatus("gemini", status, "", "plus", ws, fetched)


class T(unittest.TestCase):
    def test_interval(self):
        self.assertEqual(next_interval("ok", 600, 1200), 600)
        self.assertEqual(next_interval("error", 600, 600), 1200)
        self.assertEqual(next_interval("error", 600, 1200), 2400 if False else 1800)
        self.assertEqual(next_interval("login_required", 600, 600), 1800)

    def test_pick_display(self):
        ok = st()
        self.assertEqual(pick_display(ok, None, NOW), (ok, False, ""))
        bad = st(status="error", fetched=NOW)
        shown, stale, sym = pick_display(bad, ok, NOW + timedelta(minutes=30))
        self.assertIs(shown, ok); self.assertTrue(stale); self.assertEqual(sym, "?")
        shown, _, _ = pick_display(bad, ok, NOW + timedelta(hours=3))
        self.assertIsNone(shown)
        shown, _, sym = pick_display(st(status="login_required"), ok, NOW)
        self.assertIsNone(shown); self.assertEqual(sym, "!")

    def test_alerts(self):
        a = AlertTracker("Gemini")
        self.assertEqual(a.update(st(session=50)), [])
        self.assertEqual(len(a.update(st(session=82))), 1)
        self.assertEqual(a.update(st(session=85)), [])          # 不重複
        self.assertEqual(len(a.update(st(session=96))), 1)      # 第二門檻
        ev = a.update(st(session=5))                            # 重設
        self.assertTrue(any("重設" in e[0] for e in ev))
        self.assertEqual(len(a.update(st(session=85))), 1)      # 重新武裝

    def test_tooltip_len(self):
        self.assertLessEqual(len(tooltip("Gemini", st())), 127)
        self.assertIn("需要重新登入", tooltip("Gemini", st(status="login_required")))


if __name__ == "__main__":
    unittest.main()


class T2(unittest.TestCase):
    def test_no_alert_on_first_sight(self):
        a = AlertTracker("Codex")
        self.assertEqual(a.update(st(session=100)), [])
        self.assertEqual(a.update(st(session=100)), [])
