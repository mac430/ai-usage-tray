"""入口（原始碼模式與打包成 exe 共用）：
  run_tray.py            = all
  run_tray.py all        啟動全部圖示（各開一個獨立程序後結束；第一次改開設定精靈）
  run_tray.py settings              打開設定頁（桌面捷徑用）
  run_tray.py gemini|codex          單獨執行一個圖示（內部使用 --single）
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
    args = [a for a in sys.argv[1:] if a != "--single"] or ["all"]
    sys.exit(main(args if args[0] in ("settings", "wizard") else ["tray"] + args))
