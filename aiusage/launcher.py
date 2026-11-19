"""啟動器：把各平台的托盤圖示各自開成獨立程序後就結束。
  all      啟動全部（Gemini、Codex）；第一次（尚未登入 Gemini）改開設定精靈
  gemini / codex / wizard   單獨啟動
每個圖示是獨立程序（有各自的單一實例鎖），重複執行不會多開；其中一個當掉也不影響其他。
Claude 的圖示由原本的 usage-monitor-for-claude 負責，不在這裡啟動。
"""
from __future__ import annotations

import subprocess
import sys

from .setup_checks import gemini_profile_exists
from .tray import winutil

PROVIDERS = ("gemini", "codex")


def spawn(key: str) -> subprocess.Popen:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(winutil.self_command(["--single", key]), creationflags=flags, close_fds=True)


def launch(keys: list[str]) -> int:
    for key in keys:
        spawn(key)
    return 0


def launch_all() -> int:
    if not gemini_profile_exists():
        spawn("wizard")       # 第一次使用：先走設定精靈，完成後由精靈啟動圖示
        return 0
    return launch(list(PROVIDERS))
