import os
import sys

from aiusage.tray import winutil


def test_icon_command_uses_dedicated_exe(tmp_path, monkeypatch):
    main = tmp_path / "AIUsageTray.exe"
    main.write_bytes(b"")
    (tmp_path / "AIUsageTray-Gemini.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(main))
    assert winutil.icon_command("gemini", ["--single", "gemini"]) == [
        os.path.join(str(tmp_path), "AIUsageTray-Gemini.exe"), "--single", "gemini"]
    # Codex 的專屬 exe 不存在 → 退回主程式
    assert winutil.icon_command("codex", ["--single", "codex"]) == [str(main), "--single", "codex"]
