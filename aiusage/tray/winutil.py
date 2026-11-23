"""Windows 專用小工具（在其他系統上安全地退化為「什麼都不做」）。"""
from __future__ import annotations

import os
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
        return [sys.executable] + args
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(pyw):
        exe = pyw
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return [exe, os.path.join(root, "run_tray.py")] + args


# 每個圖示用不同檔名的 exe 執行：Windows 依「執行檔路徑」記住托盤圖示的設定
# （顯示在工作列或收進 ^ 裡），同一個 exe 開出的兩個圖示會被綁在一起。
ICON_EXE = {"gemini": "AIUsageTray-Gemini.exe", "codex": "AIUsageTray-Codex.exe"}


def icon_command(key: str, args: list[str]) -> list[str]:
    """啟動某個圖示的指令列：打包版優先用該圖示專屬的 exe（找不到就退回主程式）。"""
    if frozen() and key in ICON_EXE:
        exe = os.path.join(os.path.dirname(sys.executable), ICON_EXE[key])
        if os.path.isfile(exe):
            return [exe] + args
    return self_command(args)


def autostart_command(key: str) -> str:
    return " ".join(f'"{p}"' if " " in p or p.endswith(".py") else p for p in self_command([key]))


def create_desktop_shortcut() -> None:
    """用 PowerShell 在桌面建立「AI 用量」捷徑（指向自己的 all 啟動）。"""
    import subprocess
    cmd = self_command(["all"])
    target, args = cmd[0], " ".join(f'"{a}"' for a in cmd[1:])
    ps = (
        "$ws=New-Object -ComObject WScript.Shell;"
        "$l=$ws.CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'),'AI 用量.lnk'));"
        f"$l.TargetPath='{target}';$l.Arguments='{args}';"
        f"$l.WorkingDirectory='{os.path.dirname(target)}';$l.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
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
