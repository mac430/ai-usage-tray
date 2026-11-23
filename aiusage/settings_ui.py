"""設定頁（tkinter）：帳號登入、圖示顯示、通知、一般設定。舊的設定精靈已併進「帳號」分頁。

改動會馬上存進 settings.json，各圖示 2 秒內套用；勾選顯示某個圖示會立刻把它開起來。
第一次使用時自動打開，停在「帳號」分頁。
"""
from __future__ import annotations

import os
import queue
import shutil
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import __version__
from . import settings as cfg
from . import setup_checks as sc
from .paths import BASE_DIR, GEMINI_PROFILE_DIR
from .tray import winutil

WINDOW_TITLE = "AI 用量 設定"
PAD = {"padx": 12, "pady": 6}
WRAP = 480


class SettingsWindow(tk.Tk):
    def __init__(self, first_run: bool = False) -> None:
        super().__init__()
        self.title(WINDOW_TITLE)
        self.resizable(False, False)
        self.first_run = first_run
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._login_proc = None
        self._loading = True
        self.s = cfg.load()
        if first_run:
            self.s = cfg.save(self.s)          # 之後就不算第一次了
            if winutil.is_windows():
                winutil.set_autostart("all", True)
                winutil.create_desktop_shortcut()
        self._build()
        self._loading = False
        self.after(150, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, self.check_codex)
        self.after(300, self.check_claude)
        self.gemini_var.set("● 已有登入資料，按「檢查登入」確認目前狀態。" if sc.gemini_profile_exists()
                            else "● 尚未登入：按「開啟登入視窗」開始。")

    # ── 畫面 ───────────────────────────────────────────────
    def _build(self) -> None:
        if self.first_run:
            ttk.Label(self, text="第一次使用：請先在「帳號」分頁登入，登入成功的平台會自動出現圖示。",
                      foreground="#0b57d0", wraplength=WRAP).pack(anchor="w", **PAD)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        for title, build in (("帳號", self._tab_accounts), ("顯示", self._tab_display),
                             ("通知", self._tab_notify), ("一般", self._tab_general)):
            f = ttk.Frame(nb)
            build(f)
            nb.add(f, text=f"  {title}  ")
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", **PAD)
        ttk.Label(bottom, text="設定會自動儲存", foreground="#666").pack(side="left")
        ttk.Button(bottom, text="關閉", command=self._on_close).pack(side="right")

    def _tab_accounts(self, f: ttk.Frame) -> None:
        g = ttk.LabelFrame(f, text=" Gemini（專用 Chrome 設定檔，請登入有 Gemini 方案的 Google 帳號） ")
        g.pack(fill="x", **PAD)
        ttk.Label(g, justify="left", wraplength=WRAP, text=(
            "1. 按「開啟登入視窗」，在跳出的 Chrome 登入 Google（問要不要登入 Chrome 時選不要）。\n"
            "2. 教育或公司帳號沒有用量頁，請用自己有 Plus 的帳號。\n"
            "3. 看到「用量限制」頁面後關閉那個視窗，回來按「檢查登入」。")).pack(anchor="w", padx=10, pady=4)
        row = ttk.Frame(g); row.pack(fill="x", padx=10, pady=4)
        ttk.Button(row, text="開啟登入視窗", command=self.open_gemini_login).pack(side="left")
        self.btn_gcheck = ttk.Button(row, text="檢查登入", command=self.check_gemini)
        self.btn_gcheck.pack(side="left", padx=8)
        ttk.Button(row, text="登出", command=self.gemini_logout).pack(side="left")
        self.gemini_var = tk.StringVar(value="● 尚未檢查")
        ttk.Label(g, textvariable=self.gemini_var, wraplength=WRAP, justify="left").pack(anchor="w", padx=10, pady=(0, 8))

        c = ttk.LabelFrame(f, text=" Codex（ChatGPT 帳號） ")
        c.pack(fill="x", **PAD)
        ttk.Label(c, justify="left", wraplength=WRAP, text=(
            "使用 Codex 的登入資料（CLI、VS Code 擴充或桌面版登入過即可）。\n"
            "還沒登入：安裝 Codex CLI 後在終端機執行登入指令，再按「檢查 Codex」。")).pack(anchor="w", padx=10, pady=4)
        row = ttk.Frame(c); row.pack(fill="x", padx=10, pady=4)
        ttk.Button(row, text="檢查 Codex", command=self.check_codex).pack(side="left")
        ttk.Button(row, text="複製安裝指令", command=lambda: self._copy(sc.CODEX_INSTALL_CMD)).pack(side="left", padx=8)
        ttk.Button(row, text="複製登入指令", command=lambda: self._copy(sc.CODEX_LOGIN_CMD)).pack(side="left")
        self.codex_var = tk.StringVar(value="● 尚未檢查")
        ttk.Label(c, textvariable=self.codex_var, wraplength=WRAP, justify="left").pack(anchor="w", padx=10, pady=(0, 8))

        k = ttk.LabelFrame(f, text=" Claude ")
        k.pack(fill="x", **PAD)
        ttk.Label(k, justify="left", wraplength=WRAP, text=(
            "Claude 的圖示由 usage-monitor-for-claude 負責，這裡只檢查這台電腦有沒有 Claude Code 登入。")
        ).pack(anchor="w", padx=10, pady=4)
        self.claude_var = tk.StringVar(value="● 尚未檢查")
        ttk.Label(k, textvariable=self.claude_var, wraplength=WRAP, justify="left").pack(anchor="w", padx=10, pady=(0, 8))

    def _tab_display(self, f: ttk.Frame) -> None:
        box = ttk.LabelFrame(f, text=" 要顯示哪些圖示 ")
        box.pack(fill="x", **PAD)
        self.var_show = {}
        for key in cfg.PROVIDER_KEYS:
            v = tk.BooleanVar(value=cfg.enabled(self.s, key))
            v.trace_add("write", lambda *_a, k=key: self._on_toggle_icon(k))
            ttk.Checkbutton(box, text=f"{cfg.PROVIDER_NAMES[key]}", variable=v).pack(anchor="w", padx=10, pady=3)
            self.var_show[key] = v
        ttk.Label(box, foreground="#666", wraplength=WRAP, justify="left", text=(
            "沒登入的平台會自動隱藏，登入後才出現。\n"
            "每個圖示可以各自拖到工作列或收進 ^ 裡。")).pack(anchor="w", padx=10, pady=(2, 8))

        box = ttk.LabelFrame(f, text=" 圖示上的數字 ")
        box.pack(fill="x", **PAD)
        self.var_used = tk.BooleanVar(value=self.s["show_used"])
        self.var_used.trace_add("write", lambda *_a: self._save(show_used=self.var_used.get()))
        ttk.Radiobutton(box, text="已使用 %（跟 Claude 圖示一樣）", value=True, variable=self.var_used).pack(anchor="w", padx=10, pady=3)
        ttk.Radiobutton(box, text="剩餘 %", value=False, variable=self.var_used).pack(anchor="w", padx=10, pady=(3, 8))

    def _tab_notify(self, f: ttk.Frame) -> None:
        box = ttk.LabelFrame(f, text=" 額度快用完時通知 ")
        box.pack(fill="x", **PAD)
        self.var_notify = tk.BooleanVar(value=self.s["notify"])
        self.var_notify.trace_add("write", lambda *_a: self._save(notify=self.var_notify.get()))
        ttk.Checkbutton(box, text="開啟通知", variable=self.var_notify).pack(anchor="w", padx=10, pady=3)
        self.var_warn = tk.IntVar(value=self.s["alert_warn"])
        self.var_crit = tk.IntVar(value=self.s["alert_crit"])
        for label, var in (("剩餘低於（%）時第一次提醒：", self.var_warn),
                           ("剩餘低於（%）時再提醒一次：", self.var_crit)):
            row = ttk.Frame(box); row.pack(fill="x", padx=10, pady=3)
            ttk.Label(row, text=label, width=26).pack(side="left")
            sp = ttk.Spinbox(row, from_=0, to=99, width=5, textvariable=var, command=self._save_thresholds)
            sp.pack(side="left")
            sp.bind("<FocusOut>", lambda _e: self._save_thresholds())
            sp.bind("<Return>", lambda _e: self._save_thresholds())
        ttk.Label(box, foreground="#666", wraplength=WRAP, text="每個門檻在每次額度重設前只通知一次。").pack(anchor="w", padx=10, pady=(2, 8))

    def _tab_general(self, f: ttk.Frame) -> None:
        box = ttk.LabelFrame(f, text=" 更新 ")
        box.pack(fill="x", **PAD)
        row = ttk.Frame(box); row.pack(fill="x", padx=10, pady=6)
        ttk.Label(row, text="每隔").pack(side="left")
        self.var_interval = tk.StringVar(value=str(self.s["interval_minutes"]))
        cb = ttk.Combobox(row, width=4, state="readonly", textvariable=self.var_interval,
                          values=[str(m) for m in cfg.INTERVAL_CHOICES])
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._save(interval_minutes=int(self.var_interval.get())))
        ttk.Label(row, text="分鐘自動更新（所有平台共用）").pack(side="left")
        ttk.Button(box, text="立即更新全部", command=lambda: cfg.request("refresh")).pack(anchor="w", padx=10, pady=(0, 8))

        box = ttk.LabelFrame(f, text=" 啟動 ")
        box.pack(fill="x", **PAD)
        self.var_autostart = tk.BooleanVar(value=winutil.autostart_enabled("all"))
        self.var_autostart.trace_add("write", lambda *_a: winutil.set_autostart("all", self.var_autostart.get()))
        ttk.Checkbutton(box, text="開機自動啟動", variable=self.var_autostart,
                        state="normal" if winutil.is_windows() else "disabled").pack(anchor="w", padx=10, pady=3)
        row = ttk.Frame(box); row.pack(fill="x", padx=10, pady=(3, 8))
        ttk.Button(row, text="建立桌面捷徑", command=self._make_shortcut).pack(side="left")
        ttk.Button(row, text="開啟記錄資料夾", command=self._open_logs).pack(side="left", padx=8)

        ttk.Label(f, foreground="#666", text=f"AI 用量 v{__version__}　·　github.com/mac430/ai-usage-tray").pack(anchor="w", **PAD)

    # ── 存設定 ─────────────────────────────────────────────
    def _save(self, **changes) -> None:
        if self._loading:
            return
        self.s = cfg.update(**changes)

    def _on_toggle_icon(self, key: str) -> None:
        if self._loading:
            return
        on = self.var_show[key].get()
        self._save(**{f"show_{key}": on})
        if on:
            from .launcher import spawn
            spawn(key)
        # 關掉：圖示自己看到設定後會結束

    def _save_thresholds(self) -> None:
        try:
            warn, crit = int(self.var_warn.get()), int(self.var_crit.get())
        except (tk.TclError, ValueError):
            warn, crit = self.s["alert_warn"], self.s["alert_crit"]
        self._save(alert_warn=warn, alert_crit=crit)
        self.var_warn.set(self.s["alert_warn"])     # 顯示修正後的值（例如第二門檻不能高於第一）
        self.var_crit.set(self.s["alert_crit"])

    def _make_shortcut(self) -> None:
        if winutil.is_windows():
            winutil.create_desktop_shortcut()
            messagebox.showinfo(WINDOW_TITLE, "已在桌面建立「AI 用量」捷徑（點了會打開這個設定頁）。")

    def _open_logs(self) -> None:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        if winutil.is_windows():
            os.startfile(str(BASE_DIR))  # type: ignore[attr-defined]

    # ── 背景工作 → 主執行緒 ────────────────────────────────
    def _pump(self) -> None:
        try:
            while True:
                fn = self._q.get_nowait()
                fn()
        except queue.Empty:
            pass
        self.after(150, self._pump)

    def _ui(self, fn) -> None:
        self._q.put(fn)

    def _copy(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.codex_var.set(f"● 已複製：{text}")

    # ── Gemini ─────────────────────────────────────────────
    def open_gemini_login(self) -> None:
        from .providers.gemini import launch_login_window
        try:
            sc.set_pause("gemini", True)
            self._login_proc = launch_login_window()
            self.gemini_var.set("● 登入視窗已開啟。登入完成並關閉該視窗後，按「檢查登入」。")
        except Exception as e:  # noqa: BLE001
            sc.set_pause("gemini", False)
            self.gemini_var.set(f"✖ 無法開啟 Chrome：{e}")

    def check_gemini(self) -> None:
        if self._login_proc is not None and self._login_proc.poll() is None:
            self.gemini_var.set("● 請先關閉剛才開啟的 Chrome 登入視窗，再按「檢查登入」。")
            return
        if not sc.gemini_profile_exists():
            self.gemini_var.set("● 尚未登入：按「開啟登入視窗」開始。")
            return
        self.btn_gcheck.state(["disabled"])
        self.gemini_var.set("● 檢查中…（約 10~20 秒）")
        sc.set_pause("gemini", True)          # 檢查時托盤先別讀，避免兩個 Chrome 搶同一個設定檔

        def work():
            from .providers.gemini import fetch
            return fetch()

        def done(res) -> None:
            ok, text = sc.describe(res) if not isinstance(res, Exception) else (False, f"檢查失敗：{res}")
            sc.set_pause("gemini", False)
            if ok:
                cfg.request("refresh")      # 讓隱藏中的 Gemini 圖示馬上更新、出現
            self._ui(lambda: (self.gemini_var.set(("✔ " if ok else "✖ ") + text),
                              self.btn_gcheck.state(["!disabled"])))

        sc.run_in_thread(work, done)

    def gemini_logout(self) -> None:
        if not sc.gemini_profile_exists():
            self.gemini_var.set("● 目前沒有登入。")
            return
        if not messagebox.askyesno(WINDOW_TITLE, "要登出 Gemini 嗎？\n會刪除專用 Chrome 設定檔（不影響你平常用的 Chrome）。"):
            return
        sc.set_pause("gemini", True)
        time.sleep(1.5)                       # 等背景讀取用的 Chrome 結束
        shutil.rmtree(GEMINI_PROFILE_DIR, ignore_errors=True)
        sc.set_pause("gemini", False)
        if sc.gemini_profile_exists():
            self.gemini_var.set("✖ 有檔案正在使用中，沒刪乾淨。請關閉相關的 Chrome 視窗後再按一次「登出」。")
        else:
            self.gemini_var.set("✔ 已登出。Gemini 圖示會自動隱藏。")
        cfg.request("refresh")

    # ── Codex / Claude ─────────────────────────────────────
    def check_codex(self) -> None:
        self.codex_var.set("● 檢查中…")

        def work():
            from .providers.codex import fetch
            return fetch()

        def done(res) -> None:
            ok, text = sc.describe(res) if not isinstance(res, Exception) else (False, f"檢查失敗：{res}")
            if ok:
                cfg.request("refresh")
            self._ui(lambda: self.codex_var.set(("✔ " if ok else "✖ ") + text))

        sc.run_in_thread(work, done)

    def check_claude(self) -> None:
        if sc.claude_login_exists():
            self.claude_var.set("✔ 已偵測到 Claude Code 登入")
        else:
            self.claude_var.set("✖ 找不到 Claude Code 登入：請先在這台電腦執行 claude 並登入")

    # ── 結束 ───────────────────────────────────────────────
    def _on_close(self) -> None:
        self._save_thresholds()
        sc.set_pause("gemini", False)
        self.destroy()


def _focus_existing() -> None:
    """設定頁已經開著：把它叫到最前面。"""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE)
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)        # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001
        pass


def main(first_run: bool = False) -> int:
    if not winutil.single_instance("settings"):
        _focus_existing()
        return 0
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    SettingsWindow(first_run=first_run).mainloop()
    return 0
