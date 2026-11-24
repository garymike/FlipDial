"""Clients for the extraction model.

The model gets a fixed prompt, the card images and a JSON schema. It never gets tools,
functions or retrieval, so text on a card has nothing it can trigger.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Protocol

import httpx

from flipdial.config import Settings
from flipdial.extract import prompt
from flipdial.extract.schema import json_schema

MAX_RESPONSE_BYTES = 64 * 1024


class ModelError(Exception):
    """The model could not be reached or returned something unusable. Message is log-safe."""


class Reader(Protocol):
    name: str

    def read(self, images: list[Path]) -> dict[str, Any]: ...


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _parse(text: str) -> dict[str, Any]:
    if len(text.encode()) > MAX_RESPONSE_BYTES:
        raise ModelError("response_too_large")
    text = text.strip()
    if text.startswith("```"):  # tolerate a fenced block
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelError("response_not_json") from exc
    if not isinstance(data, dict):
        raise ModelError("response_not_object")
    return data


def _http_error(exc: httpx.HTTPError) -> ModelError:
    """Turn a failed request into a reason the person can act on."""
    if isinstance(exc, httpx.TimeoutException):
        return ModelError("model_timeout")
    if isinstance(exc, httpx.HTTPStatusError):
        text = exc.response.text[:500].lower()
        if exc.response.status_code == 404 or "not found" in text:
            return ModelError("model_not_installed")
        if "image" in text or "vision" in text or "multimodal" in text:
            return ModelError("model_not_vision")
        return ModelError("model_error")
    return ModelError("model_unreachable")


class OllamaReader:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.name = f"ollama:{settings.model_name}"
        self.model = settings.model_name
        self.url = settings.model_url.rstrip("/") + "/api/chat"
        self.http = client or httpx.Client(timeout=settings.model_timeout_seconds)

    def read(self, images: list[Path]) -> dict[str, Any]:
        body = {
            "model": self.model,
            "stream": False,
            "think": False,  # reasoning adds time and nothing useful to copying card text
            "format": json_schema(),
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": prompt.SYSTEM},
                {"role": "user", "content": prompt.USER, "images": [_b64(p) for p in images]},
            ],
        }
        try:
            r = self.http.post(self.url, json=body)
            if r.status_code == 400 and "think" in r.text.lower():
                body.pop("think")  # an Ollama version or model without the switch
                r = self.http.post(self.url, json=body)
            r.raise_for_status()
            content = r.json()["message"]["content"]
        except httpx.HTTPError as exc:
            raise _http_error(exc) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelError("unexpected_response") from exc
        return _parse(content)


class OpenAICompatibleReader:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.name = f"openai:{settings.model_name}"
        self.model = settings.model_name
        self.url = settings.model_url.rstrip("/") + "/chat/completions"
        headers = {}
        if settings.model_api_key:
            headers["Authorization"] = f"Bearer {settings.model_api_key.get_secret_value()}"
        self.http = client or httpx.Client(timeout=settings.model_timeout_seconds, headers=headers)

    def read(self, images: list[Path]) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt.USER}]
        for p in images:
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_b64(p)}"}}
            )
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "card_fields", "schema": json_schema()},
            },
            "messages": [
                {"role": "system", "content": prompt.SYSTEM},
                {"role": "user", "content": content},
            ],
        }
        try:
            r = self.http.post(self.url, json=body)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        except httpx.HTTPError as exc:
            raise _http_error(exc) from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelError("unexpected_response") from exc
        return _parse(text)


def make_reader(settings: Settings, client: httpx.Client | None = None) -> Reader:
    if settings.model_backend == "openai_compatible":
        return OpenAICompatibleReader(settings, client)
    return OllamaReader(settings, client)
