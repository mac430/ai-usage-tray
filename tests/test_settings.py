import json

from aiusage import settings as cfg
from aiusage.model import ProviderStatus, UsageWindow
from aiusage.tray.logic import AlertTracker, should_hide


def test_defaults_when_missing(tmp_path):
    s = cfg.load(tmp_path / "settings.json")
    assert s == cfg.DEFAULTS


def test_normalize_fixes_bad_values(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"show_codex": False, "interval_minutes": 7, "alert_warn": 10,
                             "alert_crit": 30, "notify": "yes"}), encoding="utf-8")
    s = cfg.load(p)
    assert s["show_codex"] is False and s["show_gemini"] is True
    assert s["interval_minutes"] == 10          # 7 不在選項內 → 預設
    assert s["alert_crit"] < s["alert_warn"]    # 第二門檻不能高於第一
    assert s["notify"] is True                  # 型別錯誤 → 預設


def test_update_roundtrip(tmp_path):
    p = tmp_path / "settings.json"
    cfg.update(p, show_gemini=False, interval_minutes=5)
    s = cfg.load(p)
    assert not cfg.enabled(s, "gemini") and cfg.enabled(s, "codex") and s["interval_minutes"] == 5


def test_migrate_legacy_show_used(tmp_path):
    (tmp_path / "settings-gemini.json").write_text('{"show_used": false}', encoding="utf-8")
    assert cfg.load(tmp_path / "settings.json")["show_used"] is False


def test_hide_when_not_logged_in():
    assert should_hide(ProviderStatus("codex", "login_required", "x"))
    assert not should_hide(ProviderStatus("codex", "error", "x"))
    assert not should_hide(None)


def test_custom_thresholds():
    def st(used):
        return ProviderStatus("g", "ok", windows=[UsageWindow("session", "目前用量", used, None, "")])
    a = AlertTracker("G", (50.0, 10.0))
    assert a.update(st(10)) == []
    assert len(a.update(st(55))) == 1          # 剩 45 ≤ 50
    assert a.update(st(60)) == []
    assert len(a.update(st(92))) == 1          # 剩 8 ≤ 10
