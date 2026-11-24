"""Windows 專用小工具（在其他系統上安全地退化為「什麼都不做」）。"""
from __future__ import annotations

import os
from typing import Optional
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_mutex_handles: list = []


def is_windows() -> bool:
    return sys.platform == "win32"


def is_light_taskbar() -> bool:
    """工作列是否為淺色主題（圖示要用深色字）。"""
    if not is_windows():
        return False
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as k:
            return winreg.QueryValueEx(k, "SystemUsesLightTheme")[0] == 1
    except OSError:
        return False


def single_instance(name: str) -> bool:
    """回傳 True 表示這是第一個執行的實例；False 表示已有同名實例在跑。"""
    if not is_windows():
        return True
    import ctypes
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, f"Local\\ai-usage-tray-{name}")
    _mutex_handles.append(handle)
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def self_command(args: list[str]) -> list[str]:
    """重新執行「自己」的指令列：打包成 exe 時是 exe 本身，否則是 pythonw + run_tray.py。"""
    if frozen():
        main_exe = os.path.join(os.path.dirname(sys.executable), "AIUsageTray.exe")
        return [main_exe if os.path.isfile(main_exe) else sys.executable] + args
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(pyw):
        exe = pyw
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return [exe, os.path.join(root, "run_tray.py")] + args


# 每個圖示用不同檔名的 exe 執行：Windows 依「執行檔路徑」記住托盤圖示的設定
# （顯示在工作列或收進 ^ 裡），同一個 exe 開出的兩個圖示會被綁在一起。
ICON_EXE = {"gemini": "AIUsageTray-Gemini.exe", "codex": "AIUsageTray-Codex.exe"}


def icon_exe_name(key: str) -> str:
    """gemini-a2 → AIUsageTray-Gemini-a2.exe（其他 Gemini 帳號的 exe 在需要時才從主程式複製）。"""
    if key in ICON_EXE:
        return ICON_EXE[key]
    return "AIUsageTray-" + "-".join(p if i else p.capitalize() for i, p in enumerate(key.split("-"))) + ".exe"


def ensure_icon_exe(folder: str, key: str) -> Optional[str]:
    """確保專屬 exe 存在而且跟主程式一樣（更新後舊的複本會被換掉）；做不到就回傳 None。"""
    import shutil
    main = os.path.join(folder, "AIUsageTray.exe")
    exe = os.path.join(folder, icon_exe_name(key))
    if key in ICON_EXE:                     # 打包時就附上的兩個，不自己複製
        return exe if os.path.isfile(exe) else None
    try:
        ms = os.stat(main)
        if os.path.isfile(exe):
            es = os.stat(exe)
            if es.st_size == ms.st_size and int(es.st_mtime) == int(ms.st_mtime):
                return exe
        shutil.copy2(main, exe)
        return exe
    except OSError:
        return exe if os.path.isfile(exe) else None


def remove_icon_exe(key: str) -> None:
    if frozen() and key not in ICON_EXE:
        try:
            os.remove(os.path.join(os.path.dirname(sys.executable), icon_exe_name(key)))
        except OSError:
            pass


def icon_command(key: str, args: list[str]) -> list[str]:
    """啟動某個圖示的指令列：打包版優先用該圖示專屬的 exe（找不到就退回主程式）。"""
    if frozen():
        exe = ensure_icon_exe(os.path.dirname(sys.executable), key)
        if exe:
            return [exe] + args
    return self_command(args)


def autostart_command(key: str) -> str:
    # 開機用 autostart：只啟動圖示、不開視窗（all／直接雙擊會打開設定頁）
    return " ".join(f'"{p}"' if " " in p or p.endswith(".py") else p for p in self_command(["autostart"]))


def refresh_autostart() -> None:
    """已開啟開機啟動的話，重寫一次指令（舊版寫的是 all，或程式換了位置）。"""
    if autostart_enabled("all"):
        try:
            set_autostart("all", True)
        except OSError:
            pass


def _desktop_dir() -> str:
    if is_windows():
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)   # CSIDL_DESKTOPDIRECTORY
            if buf.value:
                return buf.value
        except Exception:  # noqa: BLE001
            pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def desktop_shortcut_exists() -> bool:
    return os.path.isfile(os.path.join(_desktop_dir(), "AI 用量.lnk"))


def create_desktop_shortcut() -> None:
    """用 PowerShell 在桌面建立「AI 用量」捷徑（打開設定頁，並啟動勾選的圖示）。
    路徑用環境變數傳給 PowerShell，不直接拼進指令：使用者名稱含 ' 之類的字元也不會壞。"""
    import subprocess
    cmd = self_command(["settings"])
    env = dict(os.environ,
               AIU_TARGET=cmd[0],
               AIU_ARGS=" ".join(f'"{a}"' for a in cmd[1:]),
               AIU_WORKDIR=os.path.dirname(cmd[0]),
               AIU_LNK=os.path.join(_desktop_dir(), "AI 用量.lnk"))
    ps = ("$ws=New-Object -ComObject WScript.Shell;"
          "$l=$ws.CreateShortcut($env:AIU_LNK);"
          "$l.TargetPath=$env:AIU_TARGET;$l.Arguments=$env:AIU_ARGS;"
          "$l.WorkingDirectory=$env:AIU_WORKDIR;$l.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)


def autostart_enabled(key: str) -> bool:
    if not is_windows():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, f"ai-usage-tray-{key}")
            return True
    except OSError:
        return False


def set_autostart(key: str, enabled: bool) -> None:
    if not is_windows():
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        for legacy in ("ai-usage-tray-gemini", "ai-usage-tray-codex"):   # 舊版各自啟動的項目
            try:
                winreg.DeleteValue(k, legacy)
            except FileNotFoundError:
                pass
        name = f"ai-usage-tray-{key}"
        if enabled:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, autostart_command(key))
        else:
            try:
                winreg.DeleteValue(k, name)
            except FileNotFoundError:
                pass
