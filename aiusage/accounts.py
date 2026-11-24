"""Gemini 多帳號：每個帳號一個專用 Chrome 設定檔。

- 第一個帳號（id = default）沿用原本的 gemini-profile 資料夾，舊版升級上來不用重新登入。
- 其他帳號放在 gemini-profile-<id>。
- 顯示方式（settings["gemini_display"]）：
    separate  每個帳號一個圖示（圖示代號 gemini、gemini-<id>，各自一個 exe 複本）
    combined  合併成一個 Gemini 圖示，數字顯示最緊的帳號，提示與選單列出全部帳號
"""
from __future__ import annotations

import re
from pathlib import Path

from .paths import BASE_DIR, GEMINI_PROFILE_DIR

DEFAULT_ID = "default"
DISPLAY_MODES = ("separate", "combined")
MAX_ACCOUNTS = 6
MAX_NAME = 16
_ID_RE = re.compile(r"^[a-z0-9]{1,8}$")


def default_accounts() -> list[dict]:
    return [{"id": DEFAULT_ID, "name": "Gemini"}]


def normalize_accounts(raw) -> list[dict]:
    """驗證帳號清單：id 唯一且只含小寫英數、名稱非空，第一個永遠是 default。"""
    out: list[dict] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for a in raw:
            if not isinstance(a, dict):
                continue
            aid, name = str(a.get("id", "")), str(a.get("name", "")).strip()[:MAX_NAME]
            if aid in seen or not (aid == DEFAULT_ID or _ID_RE.match(aid)):
                continue
            seen.add(aid)
            out.append({"id": aid, "name": name or ("Gemini" if aid == DEFAULT_ID else aid)})
    if DEFAULT_ID not in seen:
        out.insert(0, default_accounts()[0])
    else:                                     # default 排第一
        out.sort(key=lambda a: a["id"] != DEFAULT_ID)
    return out[:MAX_ACCOUNTS]


def new_id(accounts: list[dict]) -> str:
    used = {a["id"] for a in accounts}
    n = 2
    while f"a{n}" in used:
        n += 1
    return f"a{n}"


def profile_dir(account_id: str) -> Path:
    return GEMINI_PROFILE_DIR if account_id == DEFAULT_ID else BASE_DIR / f"gemini-profile-{account_id}"


def icon_key(account_id: str) -> str:
    return "gemini" if account_id == DEFAULT_ID else f"gemini-{account_id}"


def account_id_of(key: str) -> str | None:
    """圖示代號 → 帳號 id（不是 Gemini 圖示就回傳 None）。"""
    if key == "gemini":
        return DEFAULT_ID
    if key.startswith("gemini-") and _ID_RE.match(key[7:]):
        return key[7:]
    return None


def find(accounts: list[dict], account_id: str) -> dict | None:
    return next((a for a in accounts if a["id"] == account_id), None)
