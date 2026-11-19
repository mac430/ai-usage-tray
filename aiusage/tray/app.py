"""托盤程式：一個平台一個圖示、一個程序。

結構：
  poll 執行緒  ──fetch()──▶  更新狀態  ──▶  重畫圖示／提示／選單／通知
右鍵選單：資訊列（不可點）、立即更新、重新登入、開機自動啟動、結束。
左鍵（預設動作）：立即更新。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from ..model import ProviderStatus
from ..paths import BASE_DIR
from .. import setup_checks
from . import winutil
from .logic import AlertTracker, menu_lines, next_interval, pick_display, tooltip
from .render import render_icon

log = logging.getLogger("aiusage.tray")

DEFAULT_INTERVAL_SECONDS = 10 * 60


def _setup_logging(key: str) -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(BASE_DIR / f"tray-{key}.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


class TrayApp:
    def __init__(
        self, key: str, name: str,
        fetch: Callable[[], ProviderStatus],
        launch_login: Optional[Callable[[], object]] = None,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self.key, self.name = key, name
        self._fetch = fetch
        self._launch_login = launch_login
        self.base_interval = interval_seconds
        self._interval = interval_seconds

        self._lock = threading.Lock()
        self._current: Optional[ProviderStatus] = None
        self._last_ok: Optional[ProviderStatus] = None
        self._alerts = AlertTracker(name)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._login_running = False
        self._icon = None  # pystray.Icon
        self._settings_path = BASE_DIR / f"settings-{key}.json"
        self.show_used = self._load_setting("show_used", True)

    def _load_setting(self, name, default):
        try:
            return json.loads(self._settings_path.read_text(encoding="utf-8")).get(name, default)
        except Exception:
            return default

    def _save_setting(self, name, value) -> None:
        try:
            try:
                data = json.loads(self._settings_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            data[name] = value
            BASE_DIR.mkdir(parents=True, exist_ok=True)
            self._settings_path.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            log.exception("save setting failed")

    # ── 畫面更新 ────────────────────────────────────────────
    def _render(self) -> None:
        if self._icon is None:
            return
        now = datetime.now().astimezone()
        with self._lock:
            cur, last_ok = self._current, self._last_ok
        if cur is None:
            img = render_icon(None, None, light_taskbar=winutil.is_light_taskbar(), symbol="…")
            title = f"{self.name}：讀取中…"
        else:
            shown, stale, symbol = pick_display(cur, last_ok, now)
            if shown is None:
                img = render_icon(None, None, light_taskbar=winutil.is_light_taskbar(), symbol=symbol)
                title = tooltip(self.name, cur)
            else:
                s, w = shown.window("session"), shown.window("weekly")
                img = render_icon(
                    s.remaining_percent if s else None, w.remaining_percent if w else None,
                    light_taskbar=winutil.is_light_taskbar(), stale=stale, symbol=symbol,
                    show_used=self.show_used)
                title = tooltip(self.name, shown, stale, self.show_used)
        self._icon.icon = img
        self._icon.title = title
        self._icon.update_menu()

    # ── 輪詢 ────────────────────────────────────────────────
    def _poll_once(self) -> None:
        try:
            st = self._fetch()
        except Exception as e:  # fetch 理論上不丟例外，這裡是最後防線
            st = ProviderStatus(self.key, "error", f"{type(e).__name__}", fetched_at=datetime.now().astimezone())
        log.info("poll status=%s message=%s", st.status, st.message)
        with self._lock:
            self._current = st
            if st.status == "ok":
                self._last_ok = st
        self._interval = next_interval(st.status, self.base_interval, self._interval)
        self._render()
        for title, msg in self._alerts.update(st):
            self._notify(title, msg)

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            if not self._login_running and not setup_checks.is_paused(self.key):
                try:
                    self._poll_once()
                except Exception:
                    log.exception("poll loop error")
            self._wake.wait(timeout=self._interval)
            self._wake.clear()

    def _notify(self, title: str, message: str) -> None:
        try:
            if self._icon is not None:
                self._icon.notify(message, title)
        except Exception:
            log.exception("notify failed")

    # ── 選單動作 ────────────────────────────────────────────
    def on_refresh(self, icon=None, item=None) -> None:
        self._interval = self.base_interval
        self._wake.set()

    def on_login(self, icon=None, item=None) -> None:
        if self._launch_login is None or self._login_running:
            return
        threading.Thread(target=self._login_flow, daemon=True).start()

    def _login_flow(self) -> None:
        self._login_running = True
        try:
            proc = self._launch_login()
            proc.wait()  # 等使用者關閉登入視窗
        except Exception:
            log.exception("login failed")
        finally:
            self._login_running = False
            self.on_refresh()

    def on_toggle_used(self, icon=None, item=None) -> None:
        self.show_used = not self.show_used
        self._save_setting("show_used", self.show_used)
        self._render()

    def on_toggle_autostart(self, icon=None, item=None) -> None:
        winutil.set_autostart("all", not winutil.autostart_enabled("all"))

    def on_quit(self, icon=None, item=None) -> None:
        self._stop.set()
        self._wake.set()
        if self._icon is not None:
            self._icon.stop()

    # ── 選單 ────────────────────────────────────────────────
    def _build_menu(self):
        import pystray
        Item = pystray.MenuItem

        def items():
            with self._lock:
                cur = self._current
            lines = menu_lines(cur, None, self.show_used) if cur else ["讀取中…"]
            for ln in lines:
                yield Item(ln, None, enabled=False)
            yield pystray.Menu.SEPARATOR
            yield Item("立即更新", self.on_refresh, default=True)
            if self._launch_login is not None:
                yield Item("重新登入…", self.on_login)
            yield Item("圖示顯示「已使用」（取消＝顯示剩餘）", self.on_toggle_used,
                       checked=lambda item: self.show_used)
            yield Item("開機自動啟動", self.on_toggle_autostart,
                       checked=lambda item: winutil.autostart_enabled("all"),
                       visible=winutil.is_windows())
            yield Item("結束", self.on_quit)

        return pystray.Menu(items)

    # ── 啟動 ────────────────────────────────────────────────
    def run(self) -> int:
        if not winutil.single_instance(self.key):
            print(f"{self.name} 已經在執行了。")
            return 0
        _setup_logging(self.key)
        import pystray

        self._icon = pystray.Icon(
            f"ai-usage-tray-{self.key}",
            render_icon(None, None, light_taskbar=winutil.is_light_taskbar(), symbol="…"),
            f"{self.name}：讀取中…", self._build_menu(),
        )

        def setup(icon):
            icon.visible = True
            threading.Thread(target=self._poll_loop, daemon=True).start()

        log.info("start %s (interval=%ss)", self.key, self.base_interval)
        self._icon.run(setup)
        return 0
