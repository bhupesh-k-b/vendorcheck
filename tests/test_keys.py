"""Visitors can bring their own API keys: held in memory only, never shown back, removable, and switchable off."""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_ctx
from vendorcheck import config
from vendorcheck.web.app import create_app


@pytest.fixture(autouse=True)
def clean_runtime(monkeypatch):
    monkeypatch.delenv("GSTINAPI_KEY", raising=False)
    config.clear_runtime()
    yield
    config.clear_runtime()


def client():
    ctx = make_ctx()
    return TestClient(create_app(ctx), follow_redirects=False), ctx


def test_a_pasted_key_connects_the_registry_and_is_never_echoed():
    c, ctx = client()
    with c:
        assert "Use your own API keys" in c.get("/settings").text
        r = c.post("/settings/keys", data={"gstin_key": "gak_secret_value_123", "ai_provider": "gemini", "ai_key": ""})
        assert r.status_code == 303
        assert ctx.gst.configured is True
        page = c.get("/settings").text
        assert "gak_secret_value_123" not in page
        assert "Remove my keys" in page


def test_removing_keys_disconnects_them():
    c, ctx = client()
    with c:
        c.post("/settings/keys", data={"gstin_key": "gak_secret_value_123"})
        assert ctx.gst.configured
        c.post("/settings/keys/clear")
        assert not ctx.gst.configured and not config.has_runtime()


def test_a_reader_key_selects_that_provider():
    c, ctx = client()
    with c:
        c.post("/settings/keys", data={"ai_provider": "groq", "ai_key": "gsk_test_value"})
        assert config.reader_provider() == "groq" and config.groq_key() == "gsk_test_value"


def test_the_form_can_be_switched_off_for_a_deployment(monkeypatch):
    monkeypatch.setenv("ALLOW_USER_KEYS", "0")
    c, ctx = client()
    with c:
        assert "Use your own API keys" not in c.get("/settings").text
        c.post("/settings/keys", data={"gstin_key": "gak_secret_value_123"})
        assert not config.has_runtime()
