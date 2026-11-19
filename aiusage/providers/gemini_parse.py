"""解析 gemini.google.com/usage 的頁面文字（純文字處理，不需要瀏覽器，可離線測試）。

設計原則：
- 以「區段標籤」切開（目前用量 / 每週上限），每個區段內再找百分比與重設時間，
  因為兩個區段裡「百分比」和「重設時間」的先後順序不同。
- 格式看不懂就回報 parse_error，絕不顯示猜的數字。
- 標籤與時間格式支援繁中；英文為合理猜測（尚未實測），之後再校正。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from ..model import ProviderStatus, UsageWindow

PROVIDER = "gemini"

SESSION_LABELS = ["目前用量", "Current usage", "Current session"]
WEEKLY_LABELS = ["每週上限", "Weekly limit", "Weekly usage"]

LOGIN_HINTS = ["登入", "Sign in", "Log in", "Choose an account", "選擇帳戶"]

# 「已使用 37%」或 "37% used"
_PCT_RE = re.compile(
    r"(?:已使用|used)\s*(\d{1,3}(?:\.\d+)?)\s*%|(\d{1,3}(?:\.\d+)?)\s*%\s*used",
    re.I,
)
_RESET_RE = re.compile(r"(?:重設時間|重置時間|Resets?(?:\s+at|\s+on)?)\s*[:：]?\s*(.+)", re.I)
_PLAN_RE = re.compile(r"\b(PLUS|PRO|ULTRA|FREE)\b", re.I)

_ZH_TIME_RE = re.compile(
    r"^(?:(\d{1,2})月\s*(\d{1,2})日)?\s*(凌晨|上午|中午|下午|晚上)?\s*(\d{1,2}):(\d{2})$"
)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_EN_TIME_RE = re.compile(
    r"^(?:([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s*)?(\d{1,2}):(\d{2})\s*([AaPp][Mm])?$"
)


def _hour24(hour: int, period: Optional[str]) -> int:
    """把 12 小時制換成 24 小時制。period：上午/下午/AM/PM 等，None 表示已是 24 小時制。"""
    if period is None:
        return hour
    p = period.lower()
    pm = p in ("下午", "晚上", "pm")
    am = p in ("上午", "凌晨", "am")
    if p == "中午":
        return 12 if hour in (12, 0) else hour
    if pm:
        return hour if hour == 12 else hour + 12
    if am:
        return 0 if hour == 12 else hour
    return hour


def parse_reset_time(raw: str, now: datetime) -> Optional[datetime]:
    """把「上午2:14」「11月24日下午10:14」之類的文字轉成帶時區的 datetime。
    只有時間：取 now 之後最近的那一次。有月日：取今年，若已過去超過一天則取明年。
    看不懂就回傳 None。"""
    s = raw.strip().rstrip("。.").strip()
    month = day = None
    period = None
    m = _ZH_TIME_RE.match(s)
    if m:
        month = int(m.group(1)) if m.group(1) else None
        day = int(m.group(2)) if m.group(2) else None
        period = m.group(3)
        hour, minute = int(m.group(4)), int(m.group(5))
    else:
        m = _EN_TIME_RE.match(s)
        if not m:
            return None
        if m.group(1):
            mon = _MONTHS.get(m.group(1)[:3].lower())
            if not mon:
                return None
            month, day = mon, int(m.group(2))
        period = m.group(5)
        hour, minute = int(m.group(3)), int(m.group(4))

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    if period is not None and not (1 <= hour <= 12 or (hour == 0)):
        return None
    hour = _hour24(hour, period)

    try:
        if month and day:
            cand = now.replace(month=month, day=day, hour=hour, minute=minute,
                               second=0, microsecond=0)
            if cand < now - timedelta(days=1):
                cand = cand.replace(year=now.year + 1)
            return cand
        cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if cand <= now:
            cand += timedelta(days=1)
        return cand
    except ValueError:
        return None


def _find_label(text: str, labels: list[str]) -> tuple[int, str]:
    best = (-1, "")
    for lab in labels:
        i = text.find(lab)
        if i != -1 and (best[0] == -1 or i < best[0]):
            best = (i, lab)
    return best


def _pct_in(section: str) -> Optional[float]:
    m = _PCT_RE.search(section)
    if not m:
        return None
    v = float(m.group(1) or m.group(2))
    return v if 0 <= v <= 100 else None


def _reset_in(section: str) -> str:
    for line in section.splitlines():
        m = _RESET_RE.search(line)
        if m:
            return m.group(1).strip()
    return ""


def _make_window(key: str, label: str, section: str, now: datetime) -> Optional[UsageWindow]:
    pct = _pct_in(section)
    if pct is None:
        return None
    raw = _reset_in(section)
    return UsageWindow(
        key=key, label=label, used_percent=pct,
        resets_at=parse_reset_time(raw, now) if raw else None, resets_raw=raw,
    )


def parse_usage_text(text: str, now: datetime, final_url: str = "") -> ProviderStatus:
    """text：頁面 body 的文字；now：帶時區的目前時間；final_url：瀏覽器最後停留的網址。"""
    def status(st: str, msg: str = "", **kw) -> ProviderStatus:
        return ProviderStatus(provider=PROVIDER, status=st, message=msg,
                              fetched_at=now, **kw)

    if final_url and "gemini.google.com/usage" not in final_url:
        return status("login_required", f"被導向別的網址（{final_url.split('?')[0]}），請重新登入")

    s_idx, s_lab = _find_label(text, SESSION_LABELS)
    w_idx, w_lab = _find_label(text, WEEKLY_LABELS)

    if s_idx == -1 and w_idx == -1:
        if any(h in text for h in LOGIN_HINTS) and not _PCT_RE.search(text):
            return status("login_required", "頁面看起來是登入畫面，請重新登入")
        return status("parse_error", "找不到「目前用量」「每週上限」標籤，頁面格式可能改了")

    # 依標籤位置切成區段
    marks = sorted([(s_idx, "session", s_lab), (w_idx, "weekly", w_lab)])
    marks = [m for m in marks if m[0] != -1]
    sections: dict[str, tuple[str, str]] = {}
    for i, (idx, key, lab) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        sections[key] = (lab, text[idx + len(lab):end])

    windows: list[UsageWindow] = []
    for key in ("session", "weekly"):
        if key not in sections:
            continue
        lab, sec = sections[key]
        w = _make_window(key, lab, sec, now)
        if w:
            windows.append(w)

    if len(windows) != 2:
        return status("parse_error",
                      f"只解析出 {len(windows)} 組用量（需要 2 組），頁面格式可能改了")

    plan_m = _PLAN_RE.search(text[:min(s_idx if s_idx != -1 else 200, w_idx if w_idx != -1 else 200)]) \
        if (s_idx != -1 or w_idx != -1) else None
    plan = plan_m.group(1).upper() if plan_m else ""
    return status("ok", plan=plan, windows=windows)
