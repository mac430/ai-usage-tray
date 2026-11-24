from datetime import datetime, timezone

from aiusage import accounts as acc
from aiusage import settings as cfg
from aiusage.model import ProviderStatus, UsageWindow
from aiusage.providers.gemini import combine
from aiusage.tray.logic import menu_lines, should_hide, tooltip


def test_normalize_keeps_default_first_and_drops_bad():
    out = acc.normalize_accounts([
        {"id": "a2", "name": "工作"}, {"id": "default", "name": "主帳號"},
        {"id": "a2", "name": "重複"}, {"id": "../x", "name": "壞"}, "junk"])
    assert [a["id"] for a in out] == ["default", "a2"]
    assert acc.normalize_accounts(None) == acc.default_accounts()


def test_keys_and_profiles():
    assert acc.icon_key("default") == "gemini" and acc.icon_key("a2") == "gemini-a2"
    assert acc.account_id_of("gemini-a2") == "a2" and acc.account_id_of("codex") is None
    assert acc.profile_dir("a2").name == "gemini-profile-a2"
    assert acc.new_id([{"id": "default"}, {"id": "a2"}]) == "a3"


def test_enabled_by_display_mode(tmp_path):
    p = tmp_path / "s.json"
    s = cfg.update(p, gemini_accounts=[{"id": "default", "name": "主"}, {"id": "a2", "name": "副"}])
    assert cfg.icon_keys(s) == ["gemini", "gemini-a2", "codex"]
    s = cfg.update(p, gemini_display="combined")
    assert cfg.icon_keys(s) == ["gemini", "codex"]
    s = cfg.update(p, show_gemini=False)
    assert cfg.icon_keys(s) == ["codex"]


def _st(session, weekly=None, status="ok"):
    ws = [UsageWindow("session", "目前用量", session)] if session is not None else []
    if weekly is not None:
        ws.append(UsageWindow("weekly", "每週", weekly))
    return ProviderStatus("gemini", status, windows=ws, fetched_at=datetime.now(timezone.utc))


def test_combine_picks_tightest_account():
    st = combine([("主", _st(20, 40)), ("副", _st(70, 30)), ("學校", _st(None, status="login_required"))])
    assert st.status == "ok" and st.window("session").used_percent == 70 and len(st.parts) == 3
    tip = tooltip("Gemini", st)
    assert "主 20%／40%" in tip and "副 70%／30%" in tip and "學校 未登入" in tip
    assert any(line.startswith("副｜") for line in menu_lines(st))


def test_combine_all_logged_out_hides():
    st = combine([("主", _st(None, status="login_required")), ("副", _st(None, status="login_required"))])
    assert st.status == "login_required" and should_hide(st)
