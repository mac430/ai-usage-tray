"""極簡的 Chrome DevTools Protocol（CDP）讀頁面工具，取代 Playwright。

做法：用已安裝的 Chrome 以無頭模式開啟網址（--remote-debugging-port=0 讓 Chrome 自選埠號，
埠號寫在設定檔資料夾的 DevToolsActivePort），透過 WebSocket 執行 document.body.innerText 取得文字。
- 只連 127.0.0.1，不對外開放。
- Runtime.evaluate 由 DevTools 直接執行，不受頁面 Trusted Types 限制。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 不走系統代理


class CdpError(RuntimeError):
    pass


def _http_json(port: int, path: str, timeout: float = 5) -> object:
    with _LOCAL.open(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class ProfileBusy(CdpError):
    """專用設定檔正被另一個 Chrome 使用（Chrome 一啟動就把工作交給它然後自己結束）。"""


_ORPHAN_PS = (
    "$p=$env:AIU_PROFILE;"
    "$n=0;"
    "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
    "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($p) -and $_.CommandLine.Contains('--headless') } | "
    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ };"
    "$n"
)


def kill_orphan_headless(profile: Path) -> int:
    """結束還佔著這個設定檔的「背景（headless）」Chrome（例如圖示被強制關掉時留下的）。
    只動帶 --headless 的，不會關到使用者開著的登入視窗或平常用的 Chrome。回傳結束的數量。"""
    if sys.platform != "win32":
        return 0
    env = dict(os.environ, AIU_PROFILE=str(profile))     # 用環境變數傳路徑，路徑有 ' 也不會壞
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", _ORPHAN_PS], env=env,
                           capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return int((r.stdout or "0").strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return 0


def _wait_port(profile: Path, proc: subprocess.Popen, timeout: float) -> int:
    f = profile / "DevToolsActivePort"
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if proc.poll() is not None:
            raise ProfileBusy("Chrome 啟動後立即結束：Gemini 專用設定檔正被另一個 Chrome 使用"
                              "（Gemini 登入視窗還開著的話請先關閉）")
        try:
            port = int(f.read_text(encoding="utf-8").splitlines()[0])
            _http_json(port, "/json/version", timeout=2)
            return port
        except (OSError, ValueError, IndexError):
            time.sleep(0.2)
    raise CdpError("等不到 Chrome 的除錯埠")


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


class _Page:
    def __init__(self, ws_url: str) -> None:
        import websocket   # websocket-client
        self._ws = websocket.create_connection(ws_url, timeout=15, suppress_origin=True)
        self._id = 0

    def call(self, method: str, params: Optional[dict] = None) -> dict:
        self._id += 1
        my = self._id
        self._ws.send(json.dumps({"id": my, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self._ws.recv())
            if msg.get("id") == my:
                if "error" in msg:
                    raise CdpError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})

    def eval_str(self, expr: str) -> str:
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        v = r.get("result", {}).get("value")
        return v if isinstance(v, str) else ""

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:  # noqa: BLE001
            pass


def read_page_text(
    chrome: Path, profile: Path, url: str, *,
    ready: Callable[[str], bool], wait_seconds: float = 20, startup_timeout: float = 30,
    extra_args: Optional[list[str]] = None,
) -> tuple[str, str]:
    """開啟 url，輪詢頁面文字直到 ready(text) 為真或逾時。回傳 (文字, 最終網址)。失敗丟 CdpError。
    設定檔被先前殘留的背景 Chrome 佔住時，清掉它再試一次。"""
    kw = dict(ready=ready, wait_seconds=wait_seconds, startup_timeout=startup_timeout, extra_args=extra_args)
    try:
        return _read_once(chrome, profile, url, **kw)
    except ProfileBusy:
        if kill_orphan_headless(profile) == 0:
            raise
        time.sleep(1.5)
        return _read_once(chrome, profile, url, **kw)


def _read_once(
    chrome: Path, profile: Path, url: str, *,
    ready: Callable[[str], bool], wait_seconds: float, startup_timeout: float,
    extra_args: Optional[list[str]],
) -> tuple[str, str]:
    profile.mkdir(parents=True, exist_ok=True)
    try:
        (profile / "DevToolsActivePort").unlink()
    except OSError:
        pass
    args = [
        str(chrome), f"--user-data-dir={profile}", "--headless=new",
        "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
        "--no-first-run", "--no-default-browser-check", "--disable-sync",
        "--disable-blink-features=AutomationControlled", "--window-size=900,1000",
        *(extra_args or []), url,
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    page = None
    try:
        port = _wait_port(profile, proc, startup_timeout)
        targets = []
        end = time.monotonic() + 10
        while time.monotonic() < end and not targets:
            targets = [t for t in _http_json(port, "/json/list") if t.get("type") == "page"]
            if not targets:
                time.sleep(0.2)
        if not targets:
            raise CdpError("找不到頁面")
        page = _Page(targets[0]["webSocketDebuggerUrl"])
        text, end = "", time.monotonic() + wait_seconds
        while True:
            try:
                text = page.eval_str("document.body ? document.body.innerText : ''")
            except CdpError:
                text = ""   # 頁面跳轉中
            if ready(text) or time.monotonic() >= end:
                break
            time.sleep(1)
        final_url = page.eval_str("location.href")
        try:
            page.call("Browser.close")   # 讓 Chrome 正常存檔（登入 cookie）後結束
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass
        return text, final_url
    except OSError as e:
        raise CdpError(f"無法啟動或連線 Chrome：{e}") from e
    finally:
        if page is not None:
            page.close()
        _kill_tree(proc)
