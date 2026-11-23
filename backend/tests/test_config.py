import pytest
from pydantic import ValidationError

from flipdial.config import Settings


def test_defaults_are_local():
    s = Settings(_env_file=None)
    assert s.host == "127.0.0.1"
    assert s.inbox_dir == s.data_dir / "inbox"


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:11434", "http://192.168.1.20:11434", "http://gpu-box.local:11434"]
)
def test_local_model_urls_allowed(url):
    assert Settings(_env_file=None, model_url=url).model_url == url


def test_remote_model_blocked_by_default():
    with pytest.raises(ValidationError, match="outside the local network"):
        Settings(_env_file=None, model_url="https://api.example.com/v1")


def test_remote_model_allowed_when_opted_in():
    s = Settings(_env_file=None, model_url="https://api.example.com/v1", allow_remote_model=True)
    assert s.allow_remote_model


def test_secrets_hidden_in_repr():
    s = Settings(_env_file=None, carddav_password="hunter2-example")
    assert "hunter2-example" not in repr(s)
