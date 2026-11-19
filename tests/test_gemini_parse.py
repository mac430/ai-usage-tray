import unittest
from datetime import datetime, timezone, timedelta

from aiusage.providers.gemini_parse import parse_usage_text, parse_reset_time

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 19, 22, 50, tzinfo=TZ)

# 使用者在 2026-11-19 實測貼上的頁面文字
REAL = """Gemini
> 用量限制
> PLUS

> 方案限制決定了你在一段時間內可使用的 Gemini 額度。進階模型和功能可能需要更高的用量。瞭解詳情

  剛才更新

> 目前用量
  info
> 已使用 37%
> 重設時間：上午2:14
> 每週上限
> 重設時間：11月24日下午10:14
> 已使用 2%
> 訂閱 AI Pro 即享 2 倍用量
  每月 $650
  升級
"""

URL = "https://gemini.google.com/usage"


class ParseUsage(unittest.TestCase):
    def test_real_page(self):
        r = parse_usage_text(REAL, NOW, URL)
        self.assertEqual(r.status, "ok", r.message)
        self.assertEqual(r.plan, "PLUS")
        s, w = r.window("session"), r.window("weekly")
        self.assertEqual(s.used_percent, 37)
        self.assertEqual(s.remaining_percent, 63)
        self.assertEqual(s.resets_at, datetime(2026, 11, 20, 2, 14, tzinfo=TZ))
        self.assertEqual(w.used_percent, 2)
        self.assertEqual(w.resets_at, datetime(2026, 11, 24, 22, 14, tzinfo=TZ))

    def test_weekly_percent_before_reset(self):
        # 兩個區段內「百分比」與「重設時間」順序互換也要能解析
        t = "目前用量\n重設時間：下午8:14\n已使用 0%\n每週上限\n已使用 5%\n重設時間：11月24日下午10:14\n"
        r = parse_usage_text(t, NOW, URL)
        self.assertEqual(r.status, "ok", r.message)
        self.assertEqual(r.window("session").used_percent, 0)
        self.assertEqual(r.window("weekly").used_percent, 5)

    def test_percent_100_and_0(self):
        t = "目前用量\n已使用 100%\n重設時間：上午3:00\n每週上限\n已使用 0%\n重設時間：11月24日上午3:00"
        r = parse_usage_text(t, NOW, URL)
        self.assertEqual(r.window("session").remaining_percent, 0)
        self.assertEqual(r.window("weekly").remaining_percent, 100)

    def test_redirected_to_login(self):
        r = parse_usage_text("登入", NOW, "https://accounts.google.com/v3/signin")
        self.assertEqual(r.status, "login_required")

    def test_login_page_without_url(self):
        r = parse_usage_text("Sign in\nChoose an account", NOW, "")
        self.assertEqual(r.status, "login_required")

    def test_garbage_is_parse_error(self):
        r = parse_usage_text("Gemini\n發生錯誤，請稍後再試", NOW, URL)
        self.assertEqual(r.status, "parse_error")
        self.assertEqual(r.windows, [])

    def test_missing_one_window(self):
        r = parse_usage_text("目前用量\n已使用 10%\n重設時間：上午2:14", NOW, URL)
        self.assertEqual(r.status, "parse_error")

    def test_out_of_range_percent_rejected(self):
        t = "目前用量\n已使用 180%\n重設時間：上午2:14\n每週上限\n已使用 2%\n重設時間：11月24日下午10:14"
        r = parse_usage_text(t, NOW, URL)
        self.assertEqual(r.status, "parse_error")

    def test_unknown_reset_format_keeps_raw(self):
        t = "目前用量\n已使用 10%\n重設時間：快了\n每週上限\n已使用 2%\n重設時間：11月24日下午10:14"
        r = parse_usage_text(t, NOW, URL)
        self.assertEqual(r.status, "ok")
        self.assertIsNone(r.window("session").resets_at)
        self.assertEqual(r.window("session").resets_raw, "快了")


class ResetTime(unittest.TestCase):
    def test_midnight_and_noon(self):
        self.assertEqual(parse_reset_time("上午12:05", NOW), datetime(2026, 11, 20, 0, 5, tzinfo=TZ))
        self.assertEqual(parse_reset_time("下午12:30", NOW.replace(hour=1)),
                         datetime(2026, 11, 19, 12, 30, tzinfo=TZ))

    def test_time_only_rolls_to_tomorrow(self):
        self.assertEqual(parse_reset_time("下午8:14", NOW), datetime(2026, 11, 20, 20, 14, tzinfo=TZ))

    def test_time_only_same_day(self):
        self.assertEqual(parse_reset_time("下午11:30", NOW), datetime(2026, 11, 19, 23, 30, tzinfo=TZ))

    def test_year_rollover(self):
        now = datetime(2026, 12, 30, 12, 0, tzinfo=TZ)
        self.assertEqual(parse_reset_time("1月2日上午3:00", now), datetime(2027, 1, 2, 3, 0, tzinfo=TZ))

    def test_english(self):
        self.assertEqual(parse_reset_time("Nov 24, 10:14 PM", NOW), datetime(2026, 11, 24, 22, 14, tzinfo=TZ))
        self.assertEqual(parse_reset_time("2:14 AM", NOW), datetime(2026, 11, 20, 2, 14, tzinfo=TZ))

    def test_invalid(self):
        self.assertIsNone(parse_reset_time("快了", NOW))
        self.assertIsNone(parse_reset_time("2月30日上午3:00", NOW))
        self.assertIsNone(parse_reset_time("上午25:00", NOW))


if __name__ == "__main__":
    unittest.main()
