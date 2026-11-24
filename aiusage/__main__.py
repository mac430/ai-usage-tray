"""指令列入口（開發與除錯用）。

  python -m aiusage gemini login            第一次：在專用設定檔登入 Google
  python -m aiusage gemini once             背景讀取一次，印出整理後的結果
  python -m aiusage gemini parse-file 檔案  離線解析一份已存的頁面文字（不連網）
  python -m aiusage settings                打開設定頁（並啟動勾選的圖示）；wizard 是舊名稱
  python -m aiusage tray all                只啟動勾選的托盤圖示（開機自動啟動用）
  python -m aiusage tray gemini             啟動 Gemini 托盤圖示（gemini-<id> 是其他帳號）
  python -m aiusage codex once              讀取一次 Codex 用量（印出整理後的結果與原始回應）
  python -m aiusage tray codex              啟動 Codex 托盤圖示
"""
import json
import sys
from datetime import datetime
from pathlib import Path

from .model import ProviderStatus


def _print_human(st: ProviderStatus) -> None:
    print(f"[{st.provider}] 狀態：{st.status}" + (f"（{st.message}）" if st.message else ""))
    if st.plan:
        print(f"方案：{st.plan}")
    for w in st.windows:
        when = w.resets_at.strftime("%m/%d %H:%M") if w.resets_at else f"?（原文：{w.resets_raw}）"
        print(f"  {w.label}：已用 {w.used_percent:g}%／剩餘 {w.remaining_percent:g}%，重設 {when}")


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "tray" and argv[1] == "all":
        from .launcher import launch_all
        return launch_all()
    if len(argv) == 1 and argv[0] in ("settings", "wizard"):
        from .launcher import launch_settings
        return launch_settings()
    if len(argv) == 2 and argv[0] == "tray" and argv[1].startswith("gemini"):
        from .accounts import account_id_of
        if account_id_of(argv[1]) is None:
            print(__doc__)
            return 2
        from .launcher import spawn
        from .providers.gemini import tray_functions
        from .tray.app import TrayApp
        fetch, name_fn = tray_functions(argv[1])
        return TrayApp(argv[1], "Gemini", fetch, lambda: spawn("settings"), name_fn=name_fn).run()
    if len(argv) == 2 and argv[0] == "tray" and argv[1] == "codex":
        from .launcher import spawn
        from .providers.codex import fetch
        from .tray.app import TrayApp
        return TrayApp("codex", "Codex", fetch, lambda: spawn("settings")).run()
    if len(argv) == 2 and argv[0] == "codex" and argv[1] == "once":
        from .providers import codex
        st = codex.fetch()
        _print_human(st)
        try:  # 除錯用：只印用量相關欄位，不印 token／帳號資訊
            raw = codex.fetch_raw()
            print()
            print(json.dumps({k: raw.get(k) for k in ("plan_type", "rate_limit", "credits")},
                             ensure_ascii=False, indent=2))
        except Exception as e:  # noqa: BLE001
            print(f"（原始回應取得失敗：{type(e).__name__}）")
        return 0 if st.status == "ok" else 1
    if len(argv) < 2 or argv[0] != "gemini":
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "login":
        from .providers.gemini import run_login
        run_login()
        return 0
    if cmd == "once":
        from .providers.gemini import fetch
        st = fetch()
    elif cmd == "parse-file" and len(argv) == 3:
        from .providers.gemini_parse import parse_usage_text
        text = Path(argv[2]).read_text(encoding="utf-8")
        st = parse_usage_text(text, datetime.now().astimezone(), "https://gemini.google.com/usage")
    else:
        print(__doc__)
        return 2
    _print_human(st)
    print()
    print(st.to_json())
    return 0 if st.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
