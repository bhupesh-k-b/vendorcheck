"""Hardening found in the project audit: no script injection through the prefill link, and upload limits."""
import json

from tests.test_web import client
from vendorcheck.web import app as web_app


def test_a_crafted_prefill_link_cannot_inject_a_script():
    c, _ = client()
    with c:
        evil = json.dumps({"legal_name": "</script><script>alert(1)</script>", "gstin": "<img src=x onerror=alert(1)>"})
        page = c.get("/new", params={"prefill": evil}).text
        assert "</script><script>alert(1)" not in page and "<img src=x" not in page
        assert "\\u003c/script\\u003e" in page                                  # the value is still there, safely encoded for the page script


def test_an_oversized_upload_is_refused_with_a_message(monkeypatch):
    monkeypatch.setattr(web_app, "MAX_FILE_MB", 0)
    c, _ = client()
    with c:
        r = c.post("/submit", data={"legal_name": "Acme"}, files={"files": ("pan.pdf", b"%PDF-1.4 tiny", "application/pdf")}, follow_redirects=False)
        assert r.status_code == 303 and "/new?error=" in r.headers["location"] and "larger%20than" in r.headers["location"]


def test_too_many_files_are_refused(monkeypatch):
    monkeypatch.setattr(web_app, "MAX_FILES", 1)
    c, _ = client()
    with c:
        two = [("files", ("a.pdf", b"%PDF-1.4 a", "application/pdf")), ("files", ("b.pdf", b"%PDF-1.4 b", "application/pdf"))]
        r = c.post("/submit", data={"legal_name": "Acme"}, files=two, follow_redirects=False)
        assert r.status_code == 303 and "at%20most" in r.headers["location"]
