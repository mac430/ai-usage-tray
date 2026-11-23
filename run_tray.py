"""入口（原始碼模式與打包成 exe 共用）：
  run_tray.py / run_tray.py all / run_tray.py settings
                          打開設定頁，並啟動勾選的圖示（直接雙擊 exe、桌面捷徑、舊版捷徑都走這裡）
  run_tray.py autostart   開機自動啟動用：只啟動圖示，不開視窗（第一次使用才開設定頁）
  run_tray.py gemini|codex  單獨執行一個圖示（內部使用 --single）
"""
import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aiusage.__main__ import main  # noqa: E402

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--single"] or ["settings"]
    if args[0] in ("all", "settings", "wizard"):
        sys.exit(main(["settings"]))
    if args[0] == "autostart":
        sys.exit(main(["tray", "all"]))
    sys.exit(main(["tray"] + args))
