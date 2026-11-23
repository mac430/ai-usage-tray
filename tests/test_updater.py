import hashlib
import io
import os
import zipfile

import pytest

from aiusage import instances, updater


def test_is_newer():
    assert updater.is_newer("0.3.1", "0.3.0")
    assert updater.is_newer("v1.0.0", "0.9.9")
    assert not updater.is_newer("0.3.0", "0.3.0")
    assert not updater.is_newer("0.2.9", "0.3.0")


def test_parse_release():
    r = updater.parse_release({
        "tag_name": "v0.3.1", "html_url": "https://github.com/x/y/releases/tag/v0.3.1", "body": "notes",
        "assets": [
            {"name": "AIUsageTray-win-v0.3.1.zip", "browser_download_url": "https://github.com/z.zip"},
            {"name": "AIUsageTray-win-v0.3.1.zip.sha256", "browser_download_url": "https://github.com/z.sha256"},
        ]})
    assert (r.version, r.zip_url, r.sha256_url) == ("0.3.1", "https://github.com/z.zip", "https://github.com/z.sha256")


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _fake_get(zip_bytes, digest):
    def get(url, timeout=20):
        return f"{digest}  a.zip".encode() if url.endswith(".sha256") else zip_bytes
    return get


REL = updater.Release("0.3.1", "p", "https://github.com/a.zip", "https://github.com/a.zip.sha256")


def test_download_verifies_hash(tmp_path, monkeypatch):
    data = _zip({"AIUsageTray/AIUsageTray.exe": b"x", "AIUsageTray/_internal/a.dll": b"y"})
    monkeypatch.setattr(updater, "_get", _fake_get(data, hashlib.sha256(data).hexdigest()))
    new = updater.download_and_verify(REL, tmp_path)
    assert (new / "AIUsageTray.exe").is_file() and (new / "_internal" / "a.dll").is_file()


def test_download_rejects_bad_hash(tmp_path, monkeypatch):
    data = _zip({"AIUsageTray/AIUsageTray.exe": b"x"})
    monkeypatch.setattr(updater, "_get", _fake_get(data, "0" * 64))
    with pytest.raises(RuntimeError, match="雜湊不符"):
        updater.download_and_verify(REL, tmp_path)


def test_download_rejects_path_traversal(tmp_path, monkeypatch):
    data = _zip({"../evil.exe": b"x", "AIUsageTray/AIUsageTray.exe": b"x"})
    monkeypatch.setattr(updater, "_get", _fake_get(data, hashlib.sha256(data).hexdigest()))
    with pytest.raises(RuntimeError, match="不安全"):
        updater.download_and_verify(REL, tmp_path)


def test_download_rejects_non_github_url(tmp_path):
    bad = updater.Release("0.3.1", "p", "https://evil.example/a.zip", "https://github.com/a.sha256")
    with pytest.raises(RuntimeError, match="不是 GitHub"):
        updater.download_and_verify(bad, tmp_path)


def test_pick_stale():
    here = os.path.join("C:", os.sep, "Programs", "AIUsageTray-exe")
    old = os.path.join("C:", os.sep, "Users", "me", "Downloads", "AIUsageTray")
    procs = [
        (1, os.path.join(here, "AIUsageTray.exe")),            # 自己
        (2, os.path.join(here, "AIUsageTray-Gemini.exe")),     # 同版本圖示 → 保留
        (3, os.path.join(here, "AIUsageTray-Codex.exe")),      # 同資料夾舊版本 → 結束
        (4, os.path.join(old, "AIUsageTray.exe")),             # 別的資料夾 → 結束
        (5, os.path.join(here, "chrome.exe")),                 # 不相干 → 保留
    ]
    assert instances.pick_stale(procs, 1, here, {2: "0.3.0", 3: "0.2.1"}, "0.3.0") == [3, 4]
