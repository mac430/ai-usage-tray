"""找出並結束「別的版本」的圖示程序。

啟動時（開機自動啟動、桌面捷徑）先呼叫 stop_other_versions()：
  - 執行檔名稱是 AIUsageTray*.exe、但不在這次執行的資料夾 → 舊位置的舊版，結束。
  - 在同一個資料夾、但登記的版本跟現在不同 → 更新後殘留的舊程序，結束。
每個圖示啟動時用 register() 登記自己的 pid、版本、執行檔路徑（running-<key>.json）。
只用 Windows 內建 API（ctypes），不需要額外套件；其他系統上什麼都不做。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

from . import __version__
from .paths import BASE_DIR

log = logging.getLogger("aiusage.instances")

EXE_PREFIX = "aiusagetray"


def _running_file(key: str) -> Path:
    return BASE_DIR / f"running-{key}.json"


def register(key: str) -> None:
    try:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        _running_file(key).write_text(json.dumps(
            {"pid": os.getpid(), "version": __version__, "exe": sys.executable}), encoding="utf-8")
    except OSError:
        pass


def registered_versions() -> dict[int, str]:
    """pid → 登記的版本。"""
    out: dict[int, str] = {}
    for p in BASE_DIR.glob("running-*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out[int(d["pid"])] = str(d.get("version", ""))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return out


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def pick_stale(procs: Iterable[tuple[int, str]], my_pid: int, my_dir: str,
               versions: dict[int, str], my_version: str = __version__) -> list[int]:
    """純邏輯（可測試）：從 (pid, 執行檔完整路徑) 清單挑出要結束的 pid。"""
    stale = []
    my_dir = _norm(my_dir)
    for pid, image in procs:
        if pid == my_pid or not image:
            continue
        if not os.path.basename(image).lower().startswith(EXE_PREFIX):
            continue
        if _norm(os.path.dirname(image)) != my_dir:
            stale.append(pid)                                  # 別的資料夾的舊版
        elif pid in versions and versions[pid] != my_version:
            stale.append(pid)                                  # 同資料夾、不同版本
    return stale


# ── Windows API ──────────────────────────────────────────────
def _list_processes() -> list[tuple[int, str]]:
    import ctypes
    from ctypes import wintypes
    psapi, k32 = ctypes.windll.psapi, ctypes.windll.kernel32
    arr = (wintypes.DWORD * 4096)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed)):
        return []
    out = []
    for pid in arr[: needed.value // ctypes.sizeof(wintypes.DWORD)]:
        image = _image_path(pid, k32)
        if image:
            out.append((int(pid), image))
    return out


def _image_path(pid: int, k32=None) -> Optional[str]:
    import ctypes
    from ctypes import wintypes
    k32 = k32 or ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        k32.CloseHandle(h)


def _terminate(pid: int) -> bool:
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x0001 | 0x00100000, False, pid)   # PROCESS_TERMINATE | SYNCHRONIZE
    if not h:
        return False
    try:
        ok = bool(k32.TerminateProcess(h, 0))
        k32.WaitForSingleObject(h, 3000)
        return ok
    finally:
        k32.CloseHandle(h)


def stop_other_versions() -> list[int]:
    """結束別的版本，回傳被結束的 pid。只有打包版（exe）才做。"""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return []
    try:
        stale = pick_stale(_list_processes(), os.getpid(), os.path.dirname(sys.executable),
                           registered_versions())
    except Exception:  # noqa: BLE001
        log.exception("list processes failed")
        return []
    killed = [pid for pid in stale if _terminate(pid)]
    if killed:
        log.info("stopped old instances: %s", killed)
    return killed
