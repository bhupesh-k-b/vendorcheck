"""Smoke tests: every page renders, the submit -> run -> task flow works over HTTP."""
import re
import tempfile
import time

from fastapi.testclient import TestClient

from tests.conftest import form, make_ctx
from vendorcheck.web.app import create_app


def client():
    # a file database like production: a shared in-memory connection is not safe across the request and pipeline threads
    ctx = make_ctx(url=f"sqlite:///{tempfile.mkdtemp()}/web.db")
    ctx.sim = False
    ctx.pacing = 0
    return TestClient(create_app(ctx)), ctx


def wait_done(c, rid, tries=200):
    for _ in range(tries):
        html = c.get(f"/runs/{rid}/fragment").text
        if 'id="run-done"' in html:
            return html
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_pages_render():
    with client()[0] as c:
        for path in ["/", "/new", "/queue", "/vendors", "/settings"]:
            r = c.get(path)
            assert r.status_code == 200, path


def test_submit_runs_and_finance_flow_over_http():
    with client()[0] as c:
        r = c.post("/submit", data={**form(), "msme": "no"}, follow_redirects=False)
        assert r.status_code == 303
        rid = int(re.search(r"/runs/(\d+)", r.headers["location"]).group(1))
        html = wait_done(c, rid)
        assert "Pending" in html and "confirm the bank account" in html
        assert "Intake" in html and "Communicate" in html
        assert "idm" in html                      # identifiers are masked in the markup by default
        assert "BLUE HERON" in c.get("/").text
        c.cookies.set("vc_user", "arjun")
        tid = int(re.search(r"/tasks/(\d+)/resolve", c.get(f"/runs/{rid}").text).group(1))
        c.post(f"/tasks/{tid}/resolve", data={"outcome": "confirmed", "method": "Called the bank", "note": "ok"})
        c.cookies.set("vc_user", "neha")
        c.post(f"/tasks/{tid}/approve", data={"decision": "approve"})
        assert "Approved" in c.get("/cases/1").text
        assert "VND-0001" in c.get("/vendors").text


def test_vendor_portal_shows_only_requested_items_and_no_internal_signals():
    with client()[0] as c:
        r = c.post("/submit", data={**form(pan="AAACB1234D"), "msme": "no"}, follow_redirects=False)   # PAN != PAN in GSTIN -> R08
        rid = int(re.search(r"/runs/(\d+)", r.headers["location"]).group(1))
        wait_done(c, rid)
        token = None
        for _ in range(80):          # the vendor link appears once the decision is saved
            m = re.search(r"/v/([\w-]+)", c.get(f"/runs/{rid}").text)
            if m:
                token = m.group(1)
                break
            time.sleep(0.05)
        assert token
        page = ""
        for _ in range(60):          # the decision is saved just after the last stage event; wait for it
            page = c.get(f"/v/{token}").text
            if "What we need from you" in page:
                break
            time.sleep(0.05)
        assert "What we need from you" in page and 'name="gstin"' in page and 'name="pan"' in page
        assert 'name="bank_account"' not in page and "R08" not in page
