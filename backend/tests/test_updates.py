"""Update check and starting the updater. GitHub is faked; nothing is launched for real."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from flipdial import updates
from flipdial.app import create_app

H = {"X-FlipDial-Request": "1"}


def _github(tag: str | None, calls: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        assert request.url.host == "api.github.com"
        if tag is None:
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(
            200,
            json={
                "tag_name": tag,
                "name": f"FlipDial {tag}",
                "published_at": "2026-12-01T00:00:00Z",
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_newer_release_is_offered_and_cached(settings, monkeypatch):
    monkeypatch.setattr(updates, "__version__", "0.9.0rc1")
    calls: list = []
    info = updates.summary(settings, http=_github("v1.0.0", calls))
    assert info["available"] and info["release"]["tag"] == "v1.0.0"
    assert info["release"]["url"] == "https://github.com/garymike/FlipDial/releases/tag/v1.0.0"
    updates.summary(settings, http=_github("v1.0.0", calls))
    assert len(calls) == 1  # second call answered from the daily cache
    assert "releases/latest" in calls[0]


def test_same_or_older_not_offered(settings, monkeypatch):
    monkeypatch.setattr(updates, "__version__", "1.0.0")
    assert not updates.summary(settings, http=_github("v1.0.0"))["available"]
    assert not updates.summary(settings, force=True, http=_github("v0.9.0"))["available"]


def test_nothing_published_and_odd_tags(settings):
    assert updates.summary(settings, http=_github(None))["release"] is None
    assert updates.summary(settings, force=True, http=_github("v1.0.0; rm -rf"))["release"] is None


def test_check_can_be_turned_off(settings):
    settings.update_check = False

    def boom(request):
        raise AssertionError("no network call expected")

    info = updates.summary(settings, http=httpx.Client(transport=httpx.MockTransport(boom)))
    assert info["enabled"] is False and not info["available"]


def test_github_down_is_not_an_error(settings):
    def down(request):
        raise httpx.ConnectError("offline")

    info = updates.summary(settings, http=httpx.Client(transport=httpx.MockTransport(down)))
    assert info["error"] == "check_failed" and not info["available"]


def test_start_only_for_script_installs(settings, monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "__version__", "0.9.0rc1")
    updates.summary(settings, http=_github("v1.0.0"))  # fill the cache
    monkeypatch.delenv("FLIPDIAL_INSTALL", raising=False)
    with pytest.raises(updates.UpdateError, match="not_supported"):
        updates.start(settings)

    script = tmp_path / "scripts" / "windows" / "update.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("# updater")
    monkeypatch.setenv("FLIPDIAL_INSTALL", "windows-scripts")
    monkeypatch.setenv("FLIPDIAL_UPDATER", str(script))
    launched = []
    monkeypatch.setattr(updates.subprocess, "Popen", lambda args, **kw: launched.append(args))
    assert updates.start(settings) == "v1.0.0"
    assert launched[0][-4:] == [str(script), "-Tag", "v1.0.0", "-FromApp"]


def test_start_refuses_other_scripts_and_no_update(settings, monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "__version__", "0.9.0rc1")
    updates.summary(settings, http=_github("v1.0.0"))
    evil = tmp_path / "evil.ps1"
    evil.write_text("x")
    monkeypatch.setenv("FLIPDIAL_INSTALL", "windows-scripts")
    monkeypatch.setenv("FLIPDIAL_UPDATER", str(evil))
    with pytest.raises(updates.UpdateError, match="updater_missing"):
        updates.start(settings)
    monkeypatch.setattr(updates, "__version__", "1.0.0")
    with pytest.raises(updates.UpdateError, match="no_update"):
        updates.start(settings)


def test_api(settings, monkeypatch):
    monkeypatch.setattr(updates, "__version__", "0.9.0rc1")
    updates.summary(settings, http=_github("v1.0.0"))
    client = TestClient(create_app(settings))
    assert client.get("/api/update").json()["available"] is True
    r = client.post("/api/update/start", headers=H)
    assert r.status_code == 409 and r.json()["detail"] == "not_supported"
    assert client.post("/api/update/start").status_code == 403  # csrf header required


def test_bad_repo_setting(tmp_path):
    from flipdial.config import Settings

    with pytest.raises(ValueError, match="owner/repository"):
        Settings(_env_file=None, data_dir=tmp_path, update_repo="https://evil.example/x")


def test_launch_failure_reported(settings, monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "__version__", "0.9.0rc1")
    updates.summary(settings, http=_github("v1.0.0"))
    script = tmp_path / "update.ps1"
    script.write_text("x")
    monkeypatch.setenv("FLIPDIAL_INSTALL", "windows-scripts")
    monkeypatch.setenv("FLIPDIAL_UPDATER", str(script))

    def no_powershell(*a, **k):
        raise FileNotFoundError("powershell.exe")

    monkeypatch.setattr(updates.subprocess, "Popen", no_powershell)
    with pytest.raises(updates.UpdateError, match="launch_failed"):
        updates.start(settings)


def test_nothing_new_is_checked_again_within_the_hour(settings, monkeypatch):
    # A release published after a "nothing new" check shows up the same day, not tomorrow.
    import time as _time

    monkeypatch.setattr(updates, "__version__", "0.9.0rc1")
    calls: list = []
    assert updates.summary(settings, http=_github(None, calls))["release"] is None
    assert updates.summary(settings, http=_github(None, calls))["release"] is None
    assert len(calls) == 1  # within the hour: from the cache
    now = _time.time()
    monkeypatch.setattr(updates.time, "time", lambda: now + updates.CHECK_AGAIN_SOON + 1)
    info = updates.summary(settings, http=_github("v0.10.0", calls))
    assert len(calls) == 2 and info["available"]


def test_check_now_route_skips_the_cache(settings, monkeypatch):
    monkeypatch.setattr(updates, "__version__", "0.9.0rc1")
    updates.summary(settings, http=_github(None))  # cached: nothing published
    import types

    fake = _github("v0.10.0")
    # Only the updates module's httpx is replaced; the test client still uses the real one.
    stub = types.SimpleNamespace(Client=lambda **kw: fake, HTTPError=httpx.HTTPError)
    monkeypatch.setattr(updates, "httpx", stub)
    api = TestClient(create_app(settings))
    r = api.post("/api/update/check", headers=H)
    assert r.status_code == 200 and r.json()["available"]
