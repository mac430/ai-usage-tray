"""托盤顯示用的純邏輯（不依賴 Windows / pystray，可在任何系統測試）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..model import ProviderStatus, UsageWindow

LEVEL_OK, LEVEL_WARN, LEVEL_CRIT = "ok", "warn", "crit"

# 以「剩餘 %」判斷顏色與警示
WARN_REMAINING = 40.0      # 低於此值：黃色
CRIT_REMAINING = 15.0      # 低於此值：紅色
ALERT_THRESHOLDS = (20.0, 5.0)   # 剩餘 ≤20%、≤5% 時各通知一次（即已用 80%、95%）

STALE_AFTER_SECONDS = 2 * 3600   # 連續失敗超過 2 小時，才改顯示「!」


def level(remaining: float) -> str:
    if remaining < CRIT_REMAINING:
        return LEVEL_CRIT
    if remaining < WARN_REMAINING:
        return LEVEL_WARN
    return LEVEL_OK


def fmt_reset(w: UsageWindow, now: Optional[datetime] = None) -> str:
    if not w.resets_at:
        return w.resets_raw or "?"
    t = w.resets_at
    now = now or datetime.now(t.tzinfo)
    if t.date() == now.date():
        return t.strftime("%H:%M")
    return t.strftime("%m/%d %H:%M")


def fmt_remaining(w: UsageWindow) -> str:
    return f"{w.remaining_percent:g}%"


def fmt_pct(w: UsageWindow, show_used: bool) -> str:
    """回傳『已用 X%』或『剩 X%』。"""
    return f"已用 {w.used_percent:g}%" if show_used else f"剩 {w.remaining_percent:g}%"


def tooltip(name: str, st: ProviderStatus, stale: bool = False, show_used: bool = True) -> str:
    """Windows 托盤提示最多約 127 字元，這裡刻意精簡。"""
    head = f"{name} {st.plan.title()}".strip()
    if st.status != "ok" and not st.windows:
        return f"{head}：{_status_text(st)}"[:127]
    s, w = st.window("session"), st.window("weekly")
    parts = [head]
    if s:
        parts.append(f"{s.label} {fmt_pct(s, show_used)}（{fmt_reset(s)} 重設）")
    if w:
        parts.append(f"{w.label} {fmt_pct(w, show_used)}（{fmt_reset(w)} 重設）")
    if stale:
        parts.append("資料可能過期")
    return "｜".join(parts)[:127]


def _status_text(st: ProviderStatus) -> str:
    return {
        "login_required": "需要重新登入",
        "parse_error": "讀不懂頁面",
        "error": "讀取失敗",
    }.get(st.status, st.status) + (f"（{st.message}）" if st.message else "")


def menu_lines(st: ProviderStatus, now: Optional[datetime] = None, show_used: bool = True) -> list[str]:
    """右鍵選單上方的（不可點）資訊列。"""
    lines: list[str] = []
    for w in st.windows:
        lines.append(f"{w.label}：已用 {w.used_percent:g}%（剩 {fmt_remaining(w)}），{fmt_reset(w, now)} 重設")
    if st.status != "ok":
        lines.append(_status_text(st))
    if st.fetched_at:
        lines.append(f"更新於 {st.fetched_at.strftime('%H:%M:%S')}")
    return lines


@dataclass
class AlertTracker:
    """剩餘額度跌破門檻時各通知一次；額度重設（剩餘明顯回升）後重新武裝。"""
    name: str
    _fired: dict[str, set[float]] = field(default_factory=dict)
    _last_remaining: dict[str, float] = field(default_factory=dict)

    def update(self, st: ProviderStatus) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        if st.status != "ok":
            return events
        for w in st.windows:
            rem = w.remaining_percent
            fired = self._fired.setdefault(w.key, set())
            last = self._last_remaining.get(w.key)
            if last is None:   # 第一次看到：已低於門檻的視為「已通知過」，避免啟動就跳通知
                fired.update(th for th in ALERT_THRESHOLDS if rem <= th)
                self._last_remaining[w.key] = rem
                continue
            if last is not None and rem > last + 10:       # 視為額度已重設
                if last <= max(ALERT_THRESHOLDS) and rem >= 50:
                    events.append((f"{self.name} 額度已重設", f"{w.label}剩餘 {rem:g}%"))
                fired.clear()
            newly = [th for th in ALERT_THRESHOLDS if rem <= th and th not in fired]
            if newly:
                fired.update(newly)   # 同時跨過多個門檻，只發一則通知
                events.append((f"{self.name} 額度剩 {rem:g}%",
                               f"{w.label}已用 {w.used_percent:g}%，{fmt_reset(w)} 重設"))
            self._last_remaining[w.key] = rem
        return events


def pick_display(current: ProviderStatus, last_ok: Optional[ProviderStatus],
                 now: datetime) -> tuple[Optional[ProviderStatus], bool, str]:
    """決定圖示要畫什麼。回傳 (要畫的資料, 是否過期, 失敗時的符號)。
    - 本次成功：畫本次資料。
    - 本次失敗但 2 小時內有成功過：畫上次資料並標為過期。
    - 其他：不畫數字，畫符號（登入問題「!」，其他「?」）。"""
    if current.status == "ok":
        return current, False, ""
    symbol = "!" if current.status == "login_required" else "?"
    if last_ok and last_ok.fetched_at and \
            (now - last_ok.fetched_at).total_seconds() <= STALE_AFTER_SECONDS and \
            current.status != "login_required":
        return last_ok, True, symbol
    return None, False, symbol


MAX_BACKOFF_SECONDS = 30 * 60
LOGIN_RECHECK_SECONDS = 30 * 60


def next_interval(status: str, base: int, current: int) -> int:
    """下一次輪詢的間隔（秒）。成功：回到基本間隔；需要登入：拉長（等使用者處理）；
    其他失敗：每次加倍，最長 30 分鐘。"""
    if status == "ok":
        return base
    if status == "login_required":
        return LOGIN_RECHECK_SECONDS
    return min(max(current, base) * 2, MAX_BACKOFF_SECONDS)
