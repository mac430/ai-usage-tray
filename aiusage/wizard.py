"""設定精靈（tkinter）：引導登入 Gemini、檢查 Codex／Claude，並設定捷徑與開機啟動。
第一次執行（找不到 Gemini 專用設定檔）會自動開啟；托盤選單「重新登入…」也會開啟。"""
from __future__ import annotations

import queue
import sys
import tkinter as tk
from tkinter import ttk

from . import setup_checks as sc
from .tray import winutil

PAD = {"padx": 12, "pady": 6}


class Wizard(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AI 用量 設定精靈")
        self.resizable(False, False)
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._login_proc = None
        self._build()
        self.after(150, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, self.check_codex)
        self.after(300, self.check_claude)

    # ── 畫面 ───────────────────────────────────────────────
    def _build(self) -> None:
        ttk.Label(self, text="三個平台各自登入一次，之後都在背景自動讀取。",
                  font=("Microsoft JhengHei UI", 10)).pack(anchor="w", **PAD)

        g = ttk.LabelFrame(self, text=" ① Gemini（專用 Chrome 設定檔，登入你的 Google 帳號） ")
        g.pack(fill="x", **PAD)
        ttk.Label(g, justify="left", wraplength=470, text=(
            "按下「開啟登入視窗」會跳出一個獨立的 Chrome 視窗。\n"
            "• 若問「要登入 Chrome 嗎？」請選「不登入帳戶使用 Chrome」。\n"
            "• 登入 Google，直到看到「用量限制」頁面，然後關閉該視窗。\n"
            "• 回到這裡按「檢查登入」。")).pack(anchor="w", padx=10, pady=4)
        row = ttk.Frame(g); row.pack(fill="x", padx=10, pady=4)
        self.btn_open = ttk.Button(row, text="開啟登入視窗", command=self.open_gemini_login)
        self.btn_open.pack(side="left")
        self.btn_gcheck = ttk.Button(row, text="檢查登入", command=self.check_gemini)
        self.btn_gcheck.pack(side="left", padx=8)
        self.gemini_var = tk.StringVar(value="● 尚未檢查")
        ttk.Label(g, textvariable=self.gemini_var, wraplength=470, justify="left").pack(anchor="w", padx=10, pady=(0, 8))

        c = ttk.LabelFrame(self, text=" ② Codex（ChatGPT 帳號） ")
        c.pack(fill="x", **PAD)
        ttk.Label(c, justify="left", wraplength=470, text=(
            "使用 Codex 的登入資料（CLI、VS Code 擴充或桌面版登入過即可）。\n"
            "還沒登入的話：安裝 Codex CLI 後，在終端機執行登入，再按「檢查 Codex」。")).pack(anchor="w", padx=10, pady=4)
        row = ttk.Frame(c); row.pack(fill="x", padx=10, pady=4)
        ttk.Button(row, text="檢查 Codex", command=self.check_codex).pack(side="left")
        ttk.Button(row, text="複製安裝指令", command=lambda: self._copy(sc.CODEX_INSTALL_CMD)).pack(side="left", padx=8)
        ttk.Button(row, text="複製登入指令", command=lambda: self._copy(sc.CODEX_LOGIN_CMD)).pack(side="left")
        self.codex_var = tk.StringVar(value="● 尚未檢查")
        ttk.Label(c, textvariable=self.codex_var, wraplength=470, justify="left").pack(anchor="w", padx=10, pady=(0, 8))

        k = ttk.LabelFrame(self, text=" ③ Claude ")
        k.pack(fill="x", **PAD)
        ttk.Label(k, justify="left", wraplength=470, text=(
            "Claude 的圖示由 usage-monitor-for-claude 負責，這裡只檢查這台電腦有沒有 Claude Code 登入。")
        ).pack(anchor="w", padx=10, pady=4)
        self.claude_var = tk.StringVar(value="● 尚未檢查")
        ttk.Label(k, textvariable=self.claude_var, wraplength=470, justify="left").pack(anchor="w", padx=10, pady=(0, 8))

        opt = ttk.Frame(self); opt.pack(fill="x", **PAD)
        self.var_autostart = tk.BooleanVar(value=True)
        self.var_shortcut = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="開機自動啟動", variable=self.var_autostart).pack(side="left")
        ttk.Checkbutton(opt, text="建立桌面捷徑", variable=self.var_shortcut).pack(side="left", padx=16)

        bottom = ttk.Frame(self); bottom.pack(fill="x", **PAD)
        ttk.Button(bottom, text="完成並啟動圖示", command=self.finish).pack(side="right")
        ttk.Button(bottom, text="稍後再說", command=self._on_close).pack(side="right", padx=8)

    # ── 背景工作 → 主執行緒 ────────────────────────────────
    def _pump(self) -> None:
        try:
            while True:
                var, text = self._q.get_nowait()
                var.set(text)
        except queue.Empty:
            pass
        self.after(150, self._pump)

    def _post(self, var: tk.StringVar, text: str) -> None:
        self._q.put((var, text))

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
        self.btn_gcheck.state(["disabled"])
        self.gemini_var.set("● 檢查中…（約 10~20 秒）")

        def work():
            from .providers.gemini import fetch
            return fetch()

        def done(res) -> None:
            ok, text = sc.describe(res) if not isinstance(res, Exception) else (False, f"檢查失敗：{res}")
            self._post(self.gemini_var, ("✔ " if ok else "✖ ") + text)
            sc.set_pause("gemini", False)
            self.after(0, lambda: self.btn_gcheck.state(["!disabled"]))

        sc.run_in_thread(work, done)

    # ── Codex / Claude ─────────────────────────────────────
    def check_codex(self) -> None:
        self.codex_var.set("● 檢查中…")

        def work():
            from .providers.codex import fetch
            return fetch()

        def done(res) -> None:
            ok, text = sc.describe(res) if not isinstance(res, Exception) else (False, f"檢查失敗：{res}")
            self._post(self.codex_var, ("✔ " if ok else "✖ ") + text)

        sc.run_in_thread(work, done)

    def check_claude(self) -> None:
        if sc.claude_login_exists():
            self.claude_var.set("✔ 已偵測到 Claude Code 登入")
        else:
            self.claude_var.set("✖ 找不到 Claude Code 登入：請先在這台電腦執行 claude 並登入")

    # ── 結束 ───────────────────────────────────────────────
    def finish(self) -> None:
        from .launcher import launch
        sc.set_pause("gemini", False)
        if winutil.is_windows():
            if self.var_autostart.get():
                winutil.set_autostart("all", True)
            if self.var_shortcut.get():
                winutil.create_desktop_shortcut()
        launch(["gemini", "codex"])
        self.destroy()

    def _on_close(self) -> None:
        sc.set_pause("gemini", False)
        self.destroy()


def main() -> int:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    Wizard().mainloop()
    return 0
