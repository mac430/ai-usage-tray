"""Codex（ChatGPT 方案）用量：讀本機 Codex 的登入檔，查 chatgpt.com 的 wham/usage。

- 登入檔：%USERPROFILE%\\.codex\\auth.json（或環境變數 CODEX_HOME 指定的資料夾）
- 只「讀」token，不會去刷新或改寫登入檔（避免把你的 Codex 登入弄壞）。
  token 過期時，開一下 Codex（CLI／VS Code／桌面版）它會自動刷新，這邊就恢復。
- 介面是非公開的，格式參考 codex-switch、codex-lb 等開源專案的實作。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..model import ProviderStatus, UsageWindow

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
TIMEOUT_SECONDS = 20


def auth_path() -> Path:
    home = os.environ.get("CODEX_HOME")
    return (Path(home) if home else Path.home() / ".codex") / "auth.json"


def read_credentials(path: Optional[Path] = None) -> tuple[str, str]:
    """回傳 (access_token, account_id)。失敗丟 ValueError（訊息可直接顯示）。"""
    path = path or auth_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError("找不到 Codex 登入檔")
    except (OSError, json.JSONDecodeError):
        raise ValueError("Codex 登入檔讀取失敗")
    tokens = data.get("tokens") if isinstance(data, dict) else None
    if not isinstance(tokens, dict) or not tokens.get("access_token"):
        raise ValueError("Codex 尚未用 ChatGPT 帳號登入")
    return str(tokens["access_token"]), str(tokens.get("account_id") or "")


def window_label(seconds: Any) -> str:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "用量"
    if s <= 0:
        return "用量"
    if s % 3600 == 0 and s < 86400:
        return f"{s // 3600} 小時"
    if s == 604800:
        return "每週"
    if 28 * 86400 <= s <= 31 * 86400:
        return "每月"
    if s % 86400 == 0:
        return f"{s // 86400} 天"
    return f"{round(s / 3600)} 小時"


def _make_window(key: str, raw: Any, now: datetime) -> Optional[UsageWindow]:
    if not isinstance(raw, dict):
        return None
    used = raw.get("used_percent", raw.get("usedPercent"))
    if not isinstance(used, (int, float)) or isinstance(used, bool) or not 0 <= used <= 100:
        return None
    resets_at = None
    ts = raw.get("reset_at", raw.get("resetAt"))
    after = raw.get("reset_after_seconds", raw.get("resetAfterSeconds"))
    if isinstance(ts, (int, float)) and ts > 0:
        resets_at = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    elif isinstance(after, (int, float)) and after >= 0:
        resets_at = datetime.fromtimestamp(now.timestamp() + after, tz=timezone.utc).astimezone()
    label = window_label(raw.get("limit_window_seconds", raw.get("limitWindowSeconds")))
    return UsageWindow(key, label, float(used), resets_at, "")


def parse_usage(payload: Any, now: datetime) -> ProviderStatus:
    """把 wham/usage 的回應整理成 ProviderStatus（不亂猜：讀不到視窗就回 parse_error）。"""
    if not isinstance(payload, dict):
        return ProviderStatus("codex", "parse_error", "回應格式不對", fetched_at=now)
    plan = str(payload.get("plan_type") or "")
    rl = payload.get("rate_limit")
    if not isinstance(rl, dict):
        return ProviderStatus("codex", "parse_error", "回應沒有 rate_limit", plan, fetched_at=now)
    windows = [w for w in (
        _make_window("session", rl.get("primary_window"), now),
        _make_window("weekly", rl.get("secondary_window"), now),
    ) if w]
    if not windows:
        return ProviderStatus("codex", "parse_error", "回應沒有可用的用量視窗", plan, fetched_at=now)
    return ProviderStatus("codex", "ok", "", plan, windows, now)


def fetch_raw() -> dict:
    token, account_id = read_credentials()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "codex-cli",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    req = urllib.request.Request(USAGE_URL, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch() -> ProviderStatus:
    """永不丟例外。"""
    now = datetime.now().astimezone()
    try:
        return parse_usage(fetch_raw(), now)
    except ValueError as e:
        return ProviderStatus("codex", "login_required", str(e), fetched_at=now)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return ProviderStatus("codex", "login_required",
                                  "登入已過期，開一下 Codex 讓它自動更新", fetched_at=now)
        return ProviderStatus("codex", "error", f"HTTP {e.code}", fetched_at=now)
    except (urllib.error.URLError, TimeoutError, OSError):
        return ProviderStatus("codex", "error", "網路連不上", fetched_at=now)
    except Exception as e:  # noqa: BLE001
        return ProviderStatus("codex", "error", type(e).__name__, fetched_at=now)
