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
from .. import instances, updater
from .. import settings as cfg
from .. import setup_checks
from . import winutil
from .logic import AlertTracker, menu_lines, next_interval, pick_display, should_hide, tooltip
from .render import render_icon

log = logging.getLogger("aiusage.tray")

WATCH_SECONDS = 2
UPDATE_CHECK_DELAY = 60          # 啟動 1 分鐘後才第一次檢查更新，之後每小時看一次是否滿一天
UPDATE_POLL_SECONDS = 3600


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
        name_fn: Optional[Callable[[dict], str]] = None,
    ) -> None:
        self.key, self.name = key, name
        self._name_fn = name_fn           # 名稱跟著設定變（例如 Gemini 帳號改名）
        self._part_alerts: dict[str, AlertTracker] = {}
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
        if self._name_fn is not None:
            self.name = self._name_fn(s)

    def _watch_loop(self) -> None:
        """設定檔變了就重新讀；有人請求更新／結束就照做。"""
        last_refresh = cfg.request_time("refresh")
        next_update_check = time.time() + UPDATE_CHECK_DELAY
        while not self._stop.wait(WATCH_SECONDS):
            if time.time() >= next_update_check:
                next_update_check = time.time() + UPDATE_POLL_SECONDS
                self._maybe_check_update()
            try:
                m = cfg.mtime(cfg.settings_path())
                if m != self._settings_mtime:
                    self._settings_mtime = m
                    s = cfg.load()
                    if not cfg.enabled(s, self.key):
                        log.info("disabled in settings, quitting")
                        self.on_quit_self()
                        return
                    old = self.settings
                    old_th = cfg.thresholds(old)
                    self._apply_settings(s)
                    if cfg.thresholds(s) != old_th:
                        self._alerts = AlertTracker(self.name, cfg.thresholds(s))
                        self._part_alerts = {}
                    accounts_changed = (s["gemini_accounts"] != old["gemini_accounts"]
                                        or s["gemini_display"] != old["gemini_display"])
                    if s["interval_minutes"] != old["interval_minutes"] or (
                            self.key.startswith("gemini") and accounts_changed):
                        self.on_refresh_self()      # 間隔、帳號或顯示方式變了：重新讀一次
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

    def _maybe_check_update(self) -> None:
        """每天一次：有新版本就通知一次（同一版本只通知一次），並在右鍵選單顯示。"""
        if not self.settings.get("auto_update_check", True) or not updater.due():
            return
        try:
            rel = updater.check_now()
        except Exception as e:  # noqa: BLE001
            log.info("update check failed: %s", e)
            return
        if updater.is_newer(rel.version) and updater.load_state().get("notified") != rel.version:
            updater.save_state(notified=rel.version)
            self._notify("AI 用量有新版本", f"v{rel.version} 已推出，右鍵圖示選「有新版本」即可更新")
        self._render()

    def _paused(self) -> bool:
        """登入中暫停讀取。合併顯示的 Gemini 圖示會讀所有帳號，任何一個在登入就先不讀。"""
        if setup_checks.is_paused(self.key):
            return True
        if self.key == "gemini":
            from ..accounts import icon_key
            return any(setup_checks.is_paused(icon_key(a["id"])) for a in self.settings["gemini_accounts"])
        return False

    def _alert_events(self, st: ProviderStatus) -> list[tuple[str, str]]:
        """合併顯示多個帳號時，每個帳號各自計算通知。"""
        if not st.parts:
            return self._alerts.update(st)
        out: list[tuple[str, str]] = []
        for pname, p in st.parts:
            t = self._part_alerts.get(pname)
            if t is None:
                t = self._part_alerts[pname] = AlertTracker(f"{self.name}（{pname}）", self._alerts.thresholds)
            out += t.update(p)
        return out

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
        for title, msg in self._alert_events(st):
            if self.notify_on:
                self._notify(title, msg)

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            if not self._paused():
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
            newer = updater.available_version()
            if newer and self._open_settings is not None:
                yield Item(f"★ 有新版本 v{newer}（點這裡更新）", self.on_settings)
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
        instances.register(self.key)
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
