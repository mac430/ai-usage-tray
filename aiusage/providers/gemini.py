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
# 注意：Gemini 頁面啟用 Trusted Types，不能用 page.wait_for_function 傳字串（會被擋），
# 所以改成在 Python 端輪詢頁面文字。
_DATA_READY_RE = re.compile(r"(已使用|used)\s*\d+\s*%|\d+\s*%\s*used", re.I)
POLL_INTERVAL_MS = 1000


def _now() -> datetime:
    return datetime.now().astimezone()


def find_chrome() -> Path:
    for p in _CHROME_CANDIDATES:
        if p.is_file():
            return p
    raise FileNotFoundError("找不到 chrome.exe")


def launch_login_window() -> subprocess.Popen:
    """非阻塞：開一個正常（無自動化旗標）的 Chrome 視窗，讓使用者在專用設定檔登入 Google。
    回傳 Popen，呼叫端可用 .wait() 等使用者關閉視窗。"""
    GEMINI_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()
    return subprocess.Popen([
        str(chrome), f"--user-data-dir={GEMINI_PROFILE_DIR}", "--no-first-run",
        "--no-default-browser-check", "--disable-sync", USAGE_URL,
    ])


def run_login() -> None:
    """命令列版：開視窗後等你按 Enter。"""
    print(f"專用設定檔：{GEMINI_PROFILE_DIR}")
    print("即將開啟獨立的 Chrome 視窗。若跳出「要登入 Chrome 嗎？」請選「不登入帳戶使用 Chrome」。")
    print("請確認能看到用量頁面，然後關閉該視窗，回到這裡按 Enter。")
    launch_login_window()
    input("登入完成並關閉 Chrome 視窗後，按 Enter ... ")


def fetch() -> ProviderStatus:
    """讀取一次。永遠回傳 ProviderStatus，不丟例外（錯誤放在 status/message）。"""
    now = _now()
    if not GEMINI_PROFILE_DIR.is_dir():
        return ProviderStatus(PROVIDER, "login_required", "尚未登入，請先執行 login", fetched_at=now)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ProviderStatus(PROVIDER, "error",
                              "缺少 playwright 套件（python -m pip install playwright）", fetched_at=now)

    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(GEMINI_PROFILE_DIR),
                channel="chrome",
                headless=True,
                ignore_default_args=["--enable-automation"],
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 900, "height": 1000},
            )
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(USAGE_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                text = ""
                waited = 0
                while True:
                    text = page.inner_text("body")
                    if _DATA_READY_RE.search(text) or waited >= WAIT_FOR_DATA_MS:
                        break  # 逾時就交給解析器判斷是登入畫面還是格式改了
                    page.wait_for_timeout(POLL_INTERVAL_MS)
                    waited += POLL_INTERVAL_MS
                final_url = page.url
            finally:
                ctx.close()
    except Exception as e:  # 瀏覽器啟動失敗、設定檔被鎖定等
        msg = str(e).splitlines()[0][:200] if str(e) else type(e).__name__
        if "user data directory is already in use" in str(e).lower() or "profile" in str(e).lower():
            msg = "專用設定檔正被另一個 Chrome 視窗使用，請先關閉它。 (" + msg + ")"
        return ProviderStatus(PROVIDER, "error", msg, fetched_at=now)

    return parse_usage_text(text, _now(), final_url)
