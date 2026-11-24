"""Gemini provider：用專用 Chrome 設定檔在背景讀取 gemini.google.com/usage。

- 不碰你平常的 Chrome 設定檔。
- 只造訪 gemini.google.com/usage。
- 讀到的頁面文字只在記憶體中解析，不寫入硬碟、不記錄 email。
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..model import ProviderStatus
from ..paths import GEMINI_PROFILE_DIR
from .gemini_parse import PROVIDER, parse_usage_text

USAGE_URL = "https://gemini.google.com/usage"
PAGE_TIMEOUT_MS = 60_000
WAIT_FOR_DATA_MS = 20_000

_CHROME_CANDIDATES = [
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
]

# 頁面出現「已使用 N%」或「N% used」就代表資料載入完成。
# 在 Python 端每秒輪詢頁面文字（Gemini 頁面啟用 Trusted Types，不在頁面內注入等待腳本）。
_DATA_READY_RE = re.compile(r"(已使用|used)\s*\d+\s*%|\d+\s*%\s*used", re.I)
POLL_INTERVAL_MS = 1000


def _now() -> datetime:
    return datetime.now().astimezone()


def find_chrome() -> Path:
    for p in _CHROME_CANDIDATES:
        if p.is_file():
            return p
    raise FileNotFoundError("找不到 chrome.exe")


def launch_login_window(profile: Optional[Path] = None) -> subprocess.Popen:
    """非阻塞：開一個正常（無自動化旗標）的 Chrome 視窗，讓使用者在專用設定檔登入 Google。
    回傳 Popen，呼叫端可用 .wait() 等使用者關閉視窗。"""
    profile = profile or GEMINI_PROFILE_DIR
    profile.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()
    # 背景讀取卡住時（例如被 Google 要求驗證）會有 headless Chrome 佔著設定檔，
    # 這時新視窗會被交給它而不顯示，所以先清掉（只動 --headless 的，不會關到使用者的視窗）。
    from .cdp import kill_orphan_headless
    kill_orphan_headless(profile)
    return subprocess.Popen([
        str(chrome), f"--user-data-dir={profile}", "--no-first-run",
        "--no-default-browser-check", "--disable-sync", USAGE_URL,
    ])


def run_login() -> None:
    """命令列版：開視窗後等你按 Enter。"""
    print(f"專用設定檔：{GEMINI_PROFILE_DIR}")
    print("即將開啟獨立的 Chrome 視窗。若跳出「要登入 Chrome 嗎？」請選「不登入帳戶使用 Chrome」。")
    print("請確認能看到用量頁面，然後關閉該視窗，回到這裡按 Enter。")
    launch_login_window()
    input("登入完成並關閉 Chrome 視窗後，按 Enter ... ")


def fetch(profile: Optional[Path] = None) -> ProviderStatus:
    """讀取一次。永遠回傳 ProviderStatus，不丟例外（錯誤放在 status/message）。"""
    now = _now()
    profile = profile or GEMINI_PROFILE_DIR
    if not profile.is_dir():
        return ProviderStatus(PROVIDER, "login_required", "尚未登入", fetched_at=now)
    try:
        from .cdp import CdpError, read_page_text
        text, final_url = read_page_text(
            find_chrome(), profile, USAGE_URL,
            ready=lambda t: bool(_DATA_READY_RE.search(t)),
            wait_seconds=WAIT_FOR_DATA_MS / 1000, startup_timeout=PAGE_TIMEOUT_MS / 1000,
        )
    except FileNotFoundError:
        return ProviderStatus(PROVIDER, "error", "找不到 Chrome，請先安裝 Google Chrome", fetched_at=now)
    except ImportError:
        return ProviderStatus(PROVIDER, "error", "缺少 websocket-client 套件", fetched_at=now)
    except CdpError as e:
        return ProviderStatus(PROVIDER, "error", str(e)[:200], fetched_at=now)
    except Exception as e:  # noqa: BLE001
        return ProviderStatus(PROVIDER, "error", f"{type(e).__name__}: {str(e)[:150]}", fetched_at=now)

    return parse_usage_text(text, _now(), final_url)


def _tightness(st: ProviderStatus) -> float:
    """越大越緊：取各時段最高的已用 %。沒有資料的帳號排最後。"""
    return max((w.used_percent for w in st.windows), default=-1.0)


def combine(parts: list[tuple[str, ProviderStatus]]) -> ProviderStatus:
    """把多個帳號的結果合成一個：圖示用最緊那個帳號的數字，其他帳號放在 parts。"""
    now = _now()
    ok = [(n, st) for n, st in parts if st.status == "ok" and st.windows]
    if ok:
        name, worst = max(ok, key=lambda p: _tightness(p[1]))
        return ProviderStatus(PROVIDER, "ok", message=f"最緊：{name}", plan=worst.plan,
                              windows=list(worst.windows), fetched_at=now, parts=parts)
    if parts and all(st.status == "login_required" for _n, st in parts):
        return ProviderStatus(PROVIDER, "login_required", "所有帳號都未登入", fetched_at=now, parts=parts)
    msg = next((st.message for _n, st in parts if st.message), "")
    return ProviderStatus(PROVIDER, "error", msg, fetched_at=now, parts=parts)


def fetch_accounts(accounts: list[dict]) -> ProviderStatus:
    """依序讀取多個帳號（一次只開一個背景 Chrome）。"""
    from ..accounts import profile_dir
    return combine([(a["name"], fetch(profile_dir(a["id"]))) for a in accounts])


def tray_functions(key: str):
    """給托盤用：依圖示代號回傳 (讀取函式, 名稱函式)。每次讀取時重新看設定，
    所以帳號改名、新增帳號、切換合併／分開顯示，不用重開程式。"""
    from .. import settings as cfg
    from ..accounts import DEFAULT_ID, account_id_of, find, profile_dir
    aid = account_id_of(key) or DEFAULT_ID

    def combined(s: dict) -> bool:
        return aid == DEFAULT_ID and s["gemini_display"] == "combined" and len(s["gemini_accounts"]) > 1

    def fetch_now() -> ProviderStatus:
        s = cfg.load()
        if combined(s):
            return fetch_accounts(s["gemini_accounts"])
        return fetch(profile_dir(aid))

    def name_fn(s: dict) -> str:
        if combined(s):
            return "Gemini"
        a = find(s["gemini_accounts"], aid)
        return a["name"] if a else "Gemini"

    return fetch_now, name_fn
