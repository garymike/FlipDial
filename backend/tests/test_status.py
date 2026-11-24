"""Setup check. The model server is faked; no network."""

from __future__ import annotations

import json

import httpx

from flipdial import status
from flipdial.extract.client import OllamaReader


def _ollama(models: dict[str, list[str] | None], up: bool = True):
    def handler(request: httpx.Request) -> httpx.Response:
        if not up:
            raise httpx.ConnectError("refused")
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n} for n in models]})
        if request.url.path == "/api/show":
            name = json.loads(request.content)["model"]
            caps = models.get(name)
            return httpx.Response(200, json={} if caps is None else {"capabilities": caps})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _by_id(result):
    return {i["id"]: i for i in result["items"]}


def test_all_good(settings):
    settings.model_name = "gemma4:12b"
    status.beat(settings, "worker")
    settings.inbox_dir.mkdir(parents=True)
    r = _by_id(status.check(settings, http=_ollama({"gemma4:12b": ["completion", "vision"]})))
    assert [r[k]["state"] for k in ("model_server", "model_installed", "model_vision")] == [
        "ok"
    ] * 3
    assert r["worker"]["state"] == "ok" and r["inbox"]["state"] == "ok"
    assert r["contacts_server"]["state"] == "warn"  # not configured


def test_ollama_down(settings):
    r = status.check(settings, http=_ollama({}, up=False))
    assert r["state"] == "fail"
    assert "isn't answering" in _by_id(r)["model_server"]["detail"]


def test_missing_model_suggests_installed_vision_models(settings):
    settings.model_name = "llama3.2-vision"
    models = {"gemma4:12b": ["vision"], "qwen3:8b": ["completion"], "qwen3.5:9b": ["vision"]}
    item = _by_id(status.check(settings, http=_ollama(models)))["model_installed"]
    assert item["state"] == "fail" and "ollama pull llama3.2-vision" in item["fix"]
    assert (
        "gemma4:12b" in item["fix"]
        and "qwen3.5:9b" in item["fix"]
        and "qwen3:8b" not in item["fix"]
    )


def test_text_only_model_and_latest_tag(settings):
    settings.model_name = "qwen3"
    r = _by_id(status.check(settings, http=_ollama({"qwen3:latest": ["completion"]})))
    assert r["model_installed"]["state"] == "ok"
    assert r["model_vision"]["state"] == "fail"


def test_worker_not_running(settings):
    r = _by_id(status.check(settings, http=_ollama({})))
    assert r["worker"]["state"] == "fail" and "start.cmd" in r["worker"]["fix"]


def test_think_switch_falls_back(settings, tmp_path):
    from PIL import Image

    img = tmp_path / "f.jpg"
    Image.new("RGB", (10, 10)).save(img)
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "think" in body:
            return httpx.Response(400, json={"error": "think value not supported"})
        return httpx.Response(
            200, json={"message": {"content": '{"full_name": {"value": "A", "confidence": 1}}'}}
        )

    reader = OllamaReader(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    reader.read([img])
    assert bodies[0]["think"] is False and "think" not in bodies[1]


def test_where_saved_names_the_server_and_last_backup(api, dav_settings):
    from flipdial import status as st

    me = api.get("/api/me").json()
    assert me["storage"] == "server" and me["server_kind"] == "server" and me["last_backup"] == ""
    for url, kind in [
        ("https://contacts.icloud.com/", "icloud"),
        ("https://www.googleapis.com/carddav/v1/principals/x/lists/default/", "google"),
        ("https://nas.local:5001/carddav/mike/", "synology"),
        ("https://dav.example/", "server"),
    ]:
        s = dav_settings.model_copy(update={"carddav_url": url})
        assert st.where_saved(s)["server_kind"] == kind
    assert api.get("/api/export/backup").status_code == 200
    assert api.get("/api/me").json()["last_backup"]
