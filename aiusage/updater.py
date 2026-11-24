"""檢查更新與安裝更新。

參考過的做法：PyUpdater（已封存）、tufup（需要自架 TUF 簽章倉庫，對這個小工具太重）、
updater4pyi（2015 年後沒維護）。共同的流程是「查最新版 → 下載 → 驗證 → 程式結束後由外部
小程式換檔 → 重新啟動」，這裡照這個流程做最小版本：
  1. 查 GitHub Releases 最新版（api.github.com，不需要登入）。
  2. 下載 zip 與 GitHub Actions 產生的 .sha256，比對雜湊，不符就放棄。
  3. 解壓到暫存資料夾，寫一支 PowerShell 小程式：等所有圖示結束 → 把新檔複製到安裝資料夾
     （只覆蓋、不刪除其他檔案）→ 重新啟動。設定與登入資料在 %LOCALAPPDATA%\\ai-usage-tray，不受影響。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import __version__
from .paths import BASE_DIR

REPO = "mac430/ai-usage-tray"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
CHECK_EVERY_SECONDS = 24 * 3600
ALLOWED_DOWNLOAD_HOSTS = ("https://github.com/", "https://objects.githubusercontent.com/",
                          "https://release-assets.githubusercontent.com/")


@dataclass
class Release:
    version: str            # 例如 "0.3.1"
    page_url: str
    zip_url: str = ""
    sha256_url: str = ""
    notes: str = ""


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-")[0])
    return tuple(int(n) for n in nums[:3]) or (0,)


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def parse_release(data: dict) -> Release:
    tag = str(data.get("tag_name", "")).lstrip("vV")
    rel = Release(version=tag, page_url=data.get("html_url") or RELEASES_PAGE,
                  notes=(data.get("body") or "")[:2000])
    for a in data.get("assets") or []:
        name, url = a.get("name", ""), a.get("browser_download_url", "")
        if name.lower().endswith(".zip") and "win" in name.lower():
            rel.zip_url = url
        elif name.lower().endswith(".sha256"):
            rel.sha256_url = url
    return rel


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"ai-usage-tray/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310（網址固定為 GitHub）
        return r.read()


def fetch_latest() -> Release:
    return parse_release(json.loads(_get(LATEST_API)))


# ── 每天自動檢查一次（由任一個圖示負責，靠狀態檔避免重複） ───────────
def _state_path() -> Path:
    return BASE_DIR / "update-state.json"


def load_state() -> dict:
    try:
        d = json.loads(_state_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(**changes) -> dict:
    d = load_state()
    d.update(changes)
    try:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        _state_path().write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass
    return d


def available_version() -> Optional[str]:
    """上次檢查到、比目前新的版本（沒有就是 None）。"""
    v = load_state().get("latest")
    return v if isinstance(v, str) and is_newer(v) else None


def due(now: Optional[float] = None) -> bool:
    last = load_state().get("last_check", 0)
    return (now or time.time()) - float(last or 0) >= CHECK_EVERY_SECONDS


def check_now() -> Release:
    """立刻查一次並記下結果（給設定頁的按鈕與每日自動檢查共用）。"""
    save_state(last_check=time.time())
    rel = fetch_latest()
    save_state(latest=rel.version)
    return rel


# ── 安裝 ──────────────────────────────────────────────────────
def can_self_update() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _check_url(url: str) -> None:
    if not url.startswith(ALLOWED_DOWNLOAD_HOSTS):
        raise RuntimeError(f"下載網址不是 GitHub：{url}")


def download_and_verify(rel: Release, dest: Path,
                        progress: Callable[[str], None] = lambda _m: None) -> Path:
    """下載 zip 並比對 SHA-256，回傳解壓後含 AIUsageTray.exe 的資料夾。"""
    if not rel.zip_url or not rel.sha256_url:
        raise RuntimeError("這個版本沒有附上 zip 或雜湊檔，請到 GitHub 手動下載")
    _check_url(rel.zip_url)
    _check_url(rel.sha256_url)
    progress("下載雜湊檔…")
    expected = _get(rel.sha256_url).decode("ascii", "ignore").split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("雜湊檔格式不對")
    progress("下載新版本…")
    data = _get(rel.zip_url, timeout=120)
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError("下載的檔案雜湊不符，已放棄更新")
    zpath = dest / "update.zip"
    zpath.write_bytes(data)
    progress("解壓縮…")
    out = dest / "new"
    with zipfile.ZipFile(zpath) as z:
        for m in z.namelist():                     # 擋掉 ../ 之類跳出資料夾的路徑
            target = (out / m).resolve()
            if not str(target).startswith(str(out.resolve())):
                raise RuntimeError("壓縮檔內容不安全，已放棄更新")
        z.extractall(out)
    hits = list(out.rglob("AIUsageTray.exe"))
    if not hits:
        raise RuntimeError("壓縮檔裡找不到 AIUsageTray.exe")
    return hits[0].parent


HELPER_PS1 = r"""
param([string]$Src, [string]$Dst, [string]$Log)
$ErrorActionPreference = 'Continue'
$DstP = $Dst.TrimEnd('\') + '\'
"helper-start $(Get-Date)" | Out-File $Log -Append -Encoding utf8
$deadline = (Get-Date).AddSeconds(30)
do {
  $left = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($DstP, [StringComparison]::OrdinalIgnoreCase) -and $_.Name -like 'AIUsageTray*' }
  if (-not $left) { break }
  Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)
if ($left) { $left | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Seconds 1 }
Get-Process -Name 'AIUsageTray*' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
robocopy $Src $Dst /E /IS /IT /R:5 /W:1 /NFL /NDL /NJH /NP | Out-File $Log -Append -Encoding utf8
"robocopy exit $LASTEXITCODE" | Out-File $Log -Append -Encoding utf8
Start-Process (Join-Path $Dst 'AIUsageTray.exe') -ArgumentList 'autostart'
"done $(Get-Date)" | Out-File $Log -Append -Encoding utf8
"""


def start_install(new_dir: Path, work: Path) -> None:
    """啟動外部小程式換檔；呼叫端接著要請所有圖示結束、自己也結束。

    小程式沒有真的跑起來就丟出錯誤（不然圖示會被關掉卻沒有人換檔、也沒有人重開）。
    """
    script = work / "apply-update.ps1"
    script.write_text(HELPER_PS1, encoding="utf-8-sig")
    log = BASE_DIR / "update.log"
    try:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        log.write_text(f"launch {time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8")
    except OSError:
        pass
    # 只用 CREATE_NO_WINDOW（不要和 DETACHED_PROCESS 一起用），並把標準輸入輸出接到 NUL，
    # 否則無主控台的程式啟動 PowerShell 時可能一開就結束。CREATE_NEW_PROCESS_GROUP 讓它不隨本程式結束。
    flags = 0x08000000 | 0x00000200 if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
         "-File", str(script), "-Src", str(new_dir), "-Dst", str(install_dir()), "-Log", str(log)],
        creationflags=flags, close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if "helper-start" in log.read_text(encoding="utf-8", errors="ignore"):
                return
        except OSError:
            pass
        if proc.poll() is not None:
            time.sleep(0.5)
            try:
                if "helper-start" in log.read_text(encoding="utf-8", errors="ignore"):
                    return
            except OSError:
                pass
            raise RuntimeError(f"換檔小程式啟動後立刻結束（代碼 {proc.returncode}），請改到 GitHub 手動下載")
        time.sleep(0.3)
    raise RuntimeError("換檔小程式 10 秒內沒有啟動，請改到 GitHub 手動下載")


def prepare_and_install(rel: Release, progress: Callable[[str], None] = lambda _m: None) -> None:
    work = Path(tempfile.mkdtemp(prefix="aiusage-update-"))
    new_dir = download_and_verify(rel, work, progress)
    progress("安裝中，圖示會暫時消失，幾秒後自動重新開啟…")
    start_install(new_dir, work)


def open_release_page(url: str = RELEASES_PAGE) -> None:
    import webbrowser
    webbrowser.open(url)

