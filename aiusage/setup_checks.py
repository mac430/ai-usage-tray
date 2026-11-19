"""設定精靈用的檢查邏輯（不含畫面，可單獨測試）。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .model import ProviderStatus
from .paths import BASE_DIR, GEMINI_PROFILE_DIR, pause_file

PAUSE_MAX_AGE_SECONDS = 30 * 60
CODEX_INSTALL_CMD = "npm install -g @openai/codex"
CODEX_LOGIN_CMD = "codex login"


def set_pause(key: str, on: bool) -> None:
    p = pause_file(key)
    try:
        if on:
            BASE_DIR.mkdir(parents=True, exist_ok=True)
            p.write_text(str(time.time()), encoding="utf-8")
        else:
            p.unlink(missing_ok=True)
    except OSError:
        pass


def is_paused(key: str, now: float | None = None) -> bool:
    """暫停旗標存在且未過期（超過 30 分鐘視為殘留，忽略）。"""
    p = pause_file(key)
    try:
        age = (now or time.time()) - p.stat().st_mtime
    except OSError:
        return False
    return age < PAUSE_MAX_AGE_SECONDS


def gemini_profile_exists() -> bool:
    return GEMINI_PROFILE_DIR.is_dir()


def describe(st: ProviderStatus) -> tuple[bool, str]:
    """把讀取結果轉成（是否成功, 給使用者看的一句話）。"""
    if st.status == "ok":
        parts = [f"{w.label} 已用 {w.used_percent:g}%" for w in st.windows]
        plan = f"（{st.plan.upper()}）" if st.plan else ""
        return True, f"已連線{plan}：" + "，".join(parts)
    if st.status == "login_required":
        return False, "尚未登入" + (f"：{st.message}" if st.message else "")
    return False, f"讀取失敗（{st.status}）" + (f"：{st.message}" if st.message else "")


def claude_login_exists(home: Path | None = None) -> bool:
    return ((home or Path.home()) / ".claude" / ".credentials.json").is_file()


def run_in_thread(fn: Callable[[], object], done: Callable[[object], None]) -> None:
    """背景執行 fn，完成後在同一個背景執行緒呼叫 done（畫面層自己負責切回主執行緒）。"""
    import threading

    def work() -> None:
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001
            result = e
        done(result)

    threading.Thread(target=work, daemon=True).start()
