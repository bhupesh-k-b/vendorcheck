"""Simulated test cases: flagged, run against the simulated registry, never written to the vendor master, and routed correctly on later actions."""
import re
from dataclasses import replace

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from tests.conftest import form, make_ctx
from tests.test_web import client, wait_done
from vendorcheck import simulation
from vendorcheck.adapters.gst import RecordedGst
from vendorcheck.models import Case, VendorMaster
from vendorcheck.policy import load_policy


def test_sim_ctx_is_flagged_labelled_and_leaves_the_base_untouched():
    base = replace(make_ctx(), policy=load_policy())                         # the real policy (the shared test helper uses a simulation one)
    sim = simulation.sim_ctx(base)
    assert sim.sim is True and sim.policy.get("simulation") is True and isinstance(sim.gst, RecordedGst)
    assert sim.gst.has(simulation.KAVERI_GSTIN)
    assert base.sim is False and "simulation" not in base.policy           # the real context is not affected
    assert sim.engine is base.engine and sim.reader is base.reader          # same database and the same real document reader


def test_kaveri_registry_response_matches_the_pack():
    r = RecordedGst({simulation.KAVERI_GSTIN: simulation.kaveri_response()}).lookup(simulation.KAVERI_GSTIN)
    assert r.ok and r.mode == "recorded" and r.fields["legal_name"] == simulation.KAVERI_NAME and r.fields["status"] == "Active"


def test_a_simulated_submission_is_flagged_approved_end_to_end_and_kept_out_of_the_vendor_master():
    c, ctx = client()
    c.app.state.sim_ctx, c.app.state.sim_base = replace(ctx, sim=True), ctx          # the fixture GSTIN stands in for the synthetic registry
    with c as c:
        r = c.post("/submit", data={**form(), "msme": "no", "simulate": "1"}, follow_redirects=False)
        rid = int(re.search(r"/runs/(\d+)", r.headers["location"]).group(1))
        wait_done(c, rid)
        with Session(ctx.engine) as s:
            assert s.exec(select(Case)).first().sim is True
        assert "Simulated" in c.get("/").text and "synthetic for this fictional company" not in c.get("/cases/1").text
        c.cookies.set("vc_user", "arjun")
        tid = int(re.search(r"/tasks/(\d+)/resolve", c.get(f"/runs/{rid}").text).group(1))
        c.post(f"/tasks/{tid}/resolve", data={"outcome": "confirmed", "method": "Called the bank", "note": "ok"})
        c.cookies.set("vc_user", "neha")
        c.post(f"/tasks/{tid}/approve", data={"decision": "approve"})
        assert "Approved" in c.get("/cases/1").text
        page = c.get(f"/runs/{rid}").text                                                 # the finished item stays visible, with who confirmed and who approved
        assert 'id="completed"' in page and "Confirmed" in page and "Arjun" in page and "Neha" in page
        with Session(ctx.engine) as s:
            assert s.exec(select(VendorMaster)).all() == []                          # a simulated approval never creates a vendor record


def test_a_normal_submission_is_not_simulated():
    c, ctx = client()
    ctx.policy.pop("simulation", None)                                        # the real policy carries no simulation marker
    with c as c:
        r = c.post("/submit", data={**form(), "msme": "no"}, follow_redirects=False)
        wait_done(c, int(re.search(r"/runs/(\d+)", r.headers["location"]).group(1)))
        with Session(ctx.engine) as s:
            assert s.exec(select(Case)).first().sim is False
        assert "Simulated test case" not in c.get("/cases/1").text
