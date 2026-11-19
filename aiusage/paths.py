"""資料夾位置（沿用實驗腳本的專用設定檔，不需要重新登入）。"""
import os
from pathlib import Path

BASE_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ai-usage-tray"
GEMINI_PROFILE_DIR = BASE_DIR / "gemini-profile"


def pause_file(key: str) -> Path:
    """登入流程進行中時，托盤暫停讀取（避免兩個 Chrome 搶同一個專用設定檔）。"""
    return BASE_DIR / f"pause-{key}"
