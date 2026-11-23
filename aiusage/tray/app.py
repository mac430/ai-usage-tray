"""托盤程式：一個平台一個圖示、一個程序。

結構：
  poll 執行緒   ──fetch()──▶  更新狀態  ──▶  重畫圖示／提示／選單／通知
  watch 執行緒  每 2 秒看設定檔與請求檔，有變就套用（設定頁改了馬上生效）
沒登入時圖示整個隱藏；在設定頁登入成功後會請所有圖示立即更新，圖示就會出現。
右鍵選單：資訊列（不可點）、立即更新（全部）、設定…、結束（全部圖示）。
左鍵（預設動作）：立即更新（全部）。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from ..model import ProviderStatus
from ..paths import BASE_DIR
from .. import settings as cfg
from .. import setup_checks
from . import winutil
from .logic import AlertTracker, menu_lines, next_interval, pick_display, should_hide, tooltip
from .render import render_icon

log = logging.getLogger("aiusage.tray")

WATCH_SECONDS = 2


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
        open_settings: Optional[Callable[[], object]] = None,
    ) -> None:
        self.key, self.name = key, name
        self._fetch = fetch
        self._open_settings = open_settings

        self._lock = threading.Lock()
        self._render_lock = threading.Lock()   # poll 與 watch 兩個執行緒都會重畫
        self._current: Optional[ProviderStatus] = None
        self._last_ok: Optional[ProviderStatus] = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._icon = None  # pystray.Icon
        self._started = time.time()
        self._settings_mtime = cfg.mtime(cfg.settings_path())
        self._apply_settings(cfg.load())
        self._interval = self.base_interval
        self._alerts = AlertTracker(name, cfg.thresholds(self.settings))

    # ── 設定 ────────────────────────────────────────────────
    def _apply_settings(self, s: dict) -> None:
        self.settings = s
        self.show_used = s["show_used"]
        self.notify_on = s["notify"]
        self.base_interval = s["interval_minutes"] * 60

    def _watch_loop(self) -> None:
        """設定檔變了就重新讀；有人請求更新／結束就照做。"""
        last_refresh = cfg.request_time("refresh")
        while not self._stop.wait(WATCH_SECONDS):
            try:
                m = cfg.mtime(cfg.settings_path())
                if m != self._settings_mtime:
                    self._settings_mtime = m
                    s = cfg.load()
                    if not cfg.enabled(s, self.key):
                        log.info("disabled in settings, quitting")
                        self.on_quit_self()
                        return
                    old_interval, old_th = self.base_interval, cfg.thresholds(self.settings)
                    self._apply_settings(s)
                    if cfg.thresholds(s) != old_th:
                        self._alerts = AlertTracker(self.name, cfg.thresholds(s))
                    if self.base_interval != old_interval:
                        self.on_refresh_self()
                    self._render()
                if cfg.request_time("quit") > self._started:
                    self.on_quit_self()
                    return
                r = cfg.request_time("refresh")
                if r != last_refresh:
                    last_refresh = r
                    self.on_refresh_self()
            except Exception:
                log.exception("watch loop error")

    # ── 畫面更新 ────────────────────────────────────────────
    def _render(self) -> None:
        with self._render_lock:
            self._render_unlocked()

    def _render_unlocked(self) -> None:
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
        visible = not should_hide(cur)
        if self._icon.visible != visible:
            self._icon.visible = visible

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
            if self.notify_on:
                self._notify(title, msg)

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            if not setup_checks.is_paused(self.key):
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
    def on_refresh_self(self) -> None:
        self._interval = self.base_interval
        self._wake.set()

    def on_refresh_all(self, icon=None, item=None) -> None:
        self.on_refresh_self()
        cfg.request("refresh")      # 其他圖示（包括目前隱藏的）也一起更新

    def on_settings(self, icon=None, item=None) -> None:
        if self._open_settings is not None:
            try:
                self._open_settings()
            except Exception:
                log.exception("open settings failed")

    def on_quit_self(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._icon is not None:
            self._icon.stop()

    def on_quit_all(self, icon=None, item=None) -> None:
        cfg.request("quit")
        self.on_quit_self()

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
            yield Item("立即更新", self.on_refresh_all, default=True)
            yield Item("設定…", self.on_settings, visible=self._open_settings is not None)
            yield Item("結束（關閉所有用量圖示）", self.on_quit_all)

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
            threading.Thread(target=self._watch_loop, daemon=True).start()

        log.info("start %s (interval=%ss)", self.key, self.base_interval)
        self._icon.run(setup)
        return 0
