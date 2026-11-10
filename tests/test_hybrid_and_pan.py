"""Token-saving reader behaviour and the on-demand PAN verify."""
import pymupdf
import pytest
from sqlmodel import Session

from tests.conftest import GSTIN, NAME, PAN, form, gst_fixture, make_ctx
from tests.test_engine import case, rule, submit, tasks
from vendorcheck import config, db, storage, workflow
from vendorcheck.adapters.base import AdapterResult
from vendorcheck.reader import HybridReader


@pytest.fixture(autouse=True)
def tmp_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")


def pdf(pages: list[str], name="pack.pdf"):
    d = pymupdf.open()
    for t in pages:
        d.new_page().insert_text((50, 80), t, fontsize=10)
    return storage.store_bytes(d.tobytes(), name)


class FakeLlm:
    def __init__(self):
        self.calls = []

    def read_text(self, pages, progress=None):
        self.calls.append(dict(pages))
        n = next(iter(pages))
        return {"pages": [{"page": n, "doc_type": "other_certificate", "legible": True, "handwritten": False, "note": "ai"}],
                "fields": [{"field": "legal_name", "value": "FROM THE MODEL", "page": n, "doc_type": "other_certificate", "snippet": ""}]}


PAN_TEXT = "INCOME TAX DEPARTMENT\nGOVT. OF INDIA\nPermanent Account Number Card\nAAACB1234C\nName\nBLUE HERON TRADING PRIVATE LIMITED"
GST_TEXT = "REGISTRATION CERTIFICATE Form GST REG-06\nRegistration Number " + GSTIN + "\n1. Legal Name\nBLUE HERON TRADING PRIVATE LIMITED\n3. Constitution of Business\nPrivate Limited Company\n"
BLOB = "Some long unrelated paragraph that no rule recognises as a vendor document at all. " * 5


def test_recognised_documents_cost_zero_model_calls():
    llm = FakeLlm()
    r = HybridReader(db.make_engine("sqlite://"), llm)
    d = r.read_document(pdf([PAN_TEXT, GST_TEXT]))
    assert llm.calls == [] and d["via"] == "ocr+rules"
    kinds = {(p["page"], p["doc_type"]) for p in d["pages"]}
    assert (1, "pan_card") in kinds and (2, "gst_certificate") in kinds
    fields = {(x["doc_type"], x["field"]): x["value"] for x in d["fields"]}
    assert fields[("pan_card", "pan")] == "AAACB1234C" and fields[("gst_certificate", "gstin")] == GSTIN


def test_the_model_sees_only_the_page_the_rules_could_not_settle():
    llm = FakeLlm()
    f = pdf([PAN_TEXT, GST_TEXT])
    # an image-only page the rules cannot classify: simulate by making the model path reachable via a pan card missing its name
    r = HybridReader(db.make_engine("sqlite://"), llm)
    d = r.read_document(pdf(["INCOME TAX DEPARTMENT\nGOVT. OF INDIA\nPermanent Account Number Card\nAAACB1234C", GST_TEXT], "gap.pdf"))
    assert len(llm.calls) == 1 and list(llm.calls[0]) == [1]            # only page 1 (name missing), never page 2
    assert "REGISTRATION CERTIFICATE" not in next(iter(llm.calls[0].values()))
    assert d["via"].startswith("ocr+rules+ai(1 page")


def test_with_the_model_disabled_nothing_is_ever_called():
    r = HybridReader(db.make_engine("sqlite://"), None)
    d = r.read_document(pdf(["INCOME TAX DEPARTMENT\nGOVT. OF INDIA\nPermanent Account Number Card\nAAACB1234C"], "noname.pdf"))
    assert d["via"] == "ocr+rules"


def test_results_are_cached_by_file_hash():
    llm = FakeLlm()
    r = HybridReader(db.make_engine("sqlite://"), llm)
    f = pdf(["INCOME TAX DEPARTMENT\nGOVT. OF INDIA\nPermanent Account Number Card\nAAACB1234C"], "c.pdf")
    r.read_document(f)
    r.read_document(f)
    assert len(llm.calls) == 1


# ---------- PAN verify ----------

def pan_ctx(name=NAME, status="Active", verified=True, score=100):
    ctx = make_ctx(sim=False)
    ctx.calls = []

    def pan_verify(pan, nm=None):
        ctx.calls.append(pan)
        return AdapterResult(True, {"pan": pan, "name": name, "status": status, "verified": verified, "name_match_score": score, "name_matched": score >= 80,
                                    "level": "basic"}, "gstin.in", "live", ref="r1")
    ctx.gst.pan_verify = pan_verify
    return ctx


def test_pan_api_is_never_called_automatically():
    ctx = pan_ctx()
    submit(ctx)
    assert ctx.calls == []


def test_live_pan_verify_makes_r14_a_live_pass():
    ctx = pan_ctx()
    cid, rid = submit(ctx)
    assert workflow.verify_pan_live(ctx, cid, "priya", background=False) == ""
    assert ctx.calls == [PAN]
    with Session(ctx.engine) as s:
        run = workflow.latest_run(s, cid)
    r14 = rule(ctx, run.id, "R14")
    assert r14["result"] == "pass" and r14["mode"] == "live" and "registered to" in r14["reason"]


def test_pan_holder_name_that_differs_goes_to_procurement():
    ctx = pan_ctx(name="SOMEBODY ELSE ENTERPRISES", score=20)
    cid, rid = submit(ctx)
    workflow.verify_pan_live(ctx, cid, "priya", background=False)
    assert any(t.key == "R14:name" and t.owner == "procurement" for t in tasks(ctx, cid, "open"))


def test_pan_reported_fake_or_deactivated_rejects():
    ctx = pan_ctx(status="Deactivated")
    cid, rid = submit(ctx)
    workflow.verify_pan_live(ctx, cid, "priya", background=False)
    assert case(ctx, cid).status == "rejected"


def test_inoperative_pan_is_pending_on_the_vendor_with_a_tds_condition():
    ctx = pan_ctx(status="Inoperative")
    cid, rid = submit(ctx)
    workflow.verify_pan_live(ctx, cid, "priya", background=False)
    c = case(ctx, cid)
    assert any(i["rule"] == "R14" and i["owner"] == "vendor" for i in c.decision["open_items"])


def test_pan_verify_failure_is_reported_not_passed():
    ctx = make_ctx()
    ctx.gst.pan_verify = lambda pan, nm=None: AdapterResult(False, source="gstin.in", mode="live", error="credits", message="The GST API account is out of credits.")
    cid, rid = submit(ctx)
    assert "out of credits" in workflow.verify_pan_live(ctx, cid, "priya", background=False)
