"""全域設定（settings.json）與「請所有圖示做某件事」的請求檔。

設定頁寫檔，各圖示每 2 秒看一次檔案修改時間，有變就重新讀取，所以改了馬上生效。
這個模組不含畫面，可在任何系統測試。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from .paths import BASE_DIR

PROVIDER_KEYS = ("gemini", "codex")    # 「顯示」分頁的開關；Gemini 多帳號見 accounts.py
PROVIDER_NAMES = {"gemini": "Gemini", "codex": "Codex"}
INTERVAL_CHOICES = (5, 10, 15, 30)   # 分鐘

DEFAULTS: dict = {
    "show_gemini": True,
    "show_codex": True,
    "show_used": True,        # True＝圖示顯示已使用 %，False＝剩餘 %
    "notify": True,
    "alert_warn": 20,         # 剩餘 ≤ 這個 % 時通知
    "alert_crit": 5,          # 剩餘 ≤ 這個 % 時再通知一次
    "interval_minutes": 10,
    "auto_update_check": True,   # 每天檢查一次有沒有新版本
    "gemini_accounts": [{"id": "default", "name": "Gemini"}],
    "gemini_display": "separate",  # separate：每個帳號一個圖示；combined：合併成一個
}


def settings_path() -> Path:
    return BASE_DIR / "settings.json"


def _request_path(kind: str) -> Path:
    return BASE_DIR / f"request-{kind}"


def _clamp_int(v, lo: int, hi: int, default: int) -> int:
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def normalize(raw: dict) -> dict:
    """補上預設值並修正不合法的值（手動改壞檔案也不會讓程式掛掉）。"""
    s = dict(DEFAULTS)
    for k in ("show_gemini", "show_codex", "show_used", "notify", "auto_update_check"):
        if isinstance(raw.get(k), bool):
            s[k] = raw[k]
    s["alert_warn"] = _clamp_int(raw.get("alert_warn"), 1, 99, DEFAULTS["alert_warn"])
    s["alert_crit"] = _clamp_int(raw.get("alert_crit"), 0, 98, DEFAULTS["alert_crit"])
    if s["alert_crit"] >= s["alert_warn"]:
        s["alert_crit"] = max(0, s["alert_warn"] - 1)
    from .accounts import DISPLAY_MODES, normalize_accounts
    s["gemini_accounts"] = normalize_accounts(raw.get("gemini_accounts"))
    if raw.get("gemini_display") in DISPLAY_MODES:
        s["gemini_display"] = raw["gemini_display"]
    m = _clamp_int(raw.get("interval_minutes"), 1, 60, DEFAULTS["interval_minutes"])
    s["interval_minutes"] = m if m in INTERVAL_CHOICES else DEFAULTS["interval_minutes"]
    return s


def exists(path: Optional[Path] = None) -> bool:
    return (path or settings_path()).is_file()


def load(path: Optional[Path] = None) -> dict:
    p = path or settings_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, ValueError):
        raw = _migrate_legacy(p.parent)
    return normalize(raw)


def _migrate_legacy(base: Path) -> dict:
    """舊版每個圖示各自存 settings-<key>.json（只有 show_used），沿用 Gemini 那份。"""
    try:
        old = json.loads((base / "settings-gemini.json").read_text(encoding="utf-8"))
        if isinstance(old.get("show_used"), bool):
            return {"show_used": old["show_used"]}
    except (OSError, ValueError, AttributeError):
        pass
    return {}


def save(data: dict, path: Optional[Path] = None) -> dict:
    """寫入（先寫暫存檔再改名，避免圖示讀到寫一半的檔案）。回傳實際存下的值。"""
    p = path or settings_path()
    s = normalize(data)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return s


def update(path: Optional[Path] = None, **changes) -> dict:
    s = load(path)
    s.update(changes)
    return save(s, path)


def enabled(s: dict, key: str) -> bool:
    """這個圖示現在該不該存在。gemini-<id> 只在「每個帳號一個圖示」且該帳號還在時存在。"""
    from .accounts import DEFAULT_ID, account_id_of, find
    aid = account_id_of(key)
    if aid is not None:
        if not s.get("show_gemini", True):
            return False
        if aid == DEFAULT_ID:
            return True
        return s.get("gemini_display") == "separate" and find(s["gemini_accounts"], aid) is not None
    return bool(s.get(f"show_{key}", True))


def icon_keys(s: dict) -> list[str]:
    """設定下應該存在的所有圖示代號。"""
    from .accounts import icon_key
    keys = [icon_key(a["id"]) for a in s["gemini_accounts"]] + ["codex"]
    return [k for k in keys if enabled(s, k)]


def thresholds(s: dict) -> tuple[float, float]:
    return float(s["alert_warn"]), float(s["alert_crit"])


def mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


# ── 請求檔：設定頁或任一圖示「請所有圖示做某件事」 ─────────────
def request(kind: str) -> None:
    """kind：refresh（全部立即更新）或 quit（全部結束）。"""
    p = _request_path(kind)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def request_time(kind: str) -> float:
    return mtime(_request_path(kind))
