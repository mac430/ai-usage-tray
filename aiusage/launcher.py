"""啟動器：把各平台的托盤圖示各自開成獨立程序。
  launch_all()       開機自動啟動（autostart）：只啟動勾選的圖示；第一次使用才開設定頁
  launch_settings()  直接雙擊 exe、桌面捷徑：啟動勾選的圖示，並打開設定頁
每個圖示是獨立程序（有各自的單一實例鎖），重複執行不會多開；其中一個當掉也不影響其他。
Claude 的圖示由原本的 usage-monitor-for-claude 負責，不在這裡啟動。
"""
from __future__ import annotations

import subprocess
import sys
import time

from . import instances
from . import settings as cfg
from .setup_checks import gemini_profile_exists
from .tray import winutil


def spawn(key: str) -> subprocess.Popen:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(winutil.icon_command(key, ["--single", key]), creationflags=flags, close_fds=True)


def start_enabled_icons(s: dict | None = None) -> list[str]:
    s = s or cfg.load()
    keys = [k for k in cfg.PROVIDER_KEYS if cfg.enabled(s, k)]
    for key in keys:
        spawn(key)
    return keys


def stop_old_versions() -> None:
    """先結束別的版本（舊位置或舊版本）的圖示，免得它們佔著單一實例鎖、新版圖示出不來。"""
    if instances.stop_other_versions():
        time.sleep(1)


def is_first_run() -> bool:
    """從來沒用過：沒有設定檔，也沒有 Gemini 專用設定檔。"""
    return not cfg.exists() and not gemini_profile_exists()


def open_settings_window(first_run: bool = False) -> int:
    from .settings_ui import main as settings_main
    return settings_main(first_run=first_run)


def launch_all() -> int:
    """開機自動啟動：啟動勾選的圖示（沒登入的會自動隱藏）；第一次使用另外打開設定頁。"""
    stop_old_versions()
    winutil.refresh_autostart()
    first = is_first_run()
    start_enabled_icons()
    return open_settings_window(first_run=True) if first else 0


def launch_settings() -> int:
    """桌面捷徑：啟動勾選的圖示，並打開設定頁。"""
    stop_old_versions()
    winutil.refresh_autostart()
    first = is_first_run()
    start_enabled_icons()
    return open_settings_window(first_run=first)
