"""R24 country signals, R25 address, R26 required documents, R27/R28 commercial setup, duplicate search, unique vendor codes."""
import pymupdf
import pytest
from sqlmodel import Session

from tests.conftest import COMMERCIAL, GSTIN, NAME, PAN, form, gst_fixture, make_ctx
from tests.test_engine import case, checks, rule, submit, tasks
from vendorcheck import config, master, storage, workflow
from vendorcheck.models import VendorMaster
from vendorcheck.policy import load_policy
from vendorcheck.reader import StaticReader


@pytest.fixture(autouse=True)
def tmp_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")


def pdf(name="pack.pdf"):
    d = pymupdf.open()
    d.new_page().insert_text((50, 80), "Typed document with enough selectable text to be treated as a text layer for these tests.")
    return storage.store_bytes(d.tobytes(), name)


def pg(n, kind, foreign=False):
    return {"page": n, "doc_type": kind, "legible": True, "handwritten": False, "note": ""}


def fl(field, value, page, doc_type):
    return {"field": field, "value": value, "page": page, "doc_type": doc_type, "snippet": value}


def pack_ctx(pages, fields, mode="always", hints=None, gst=None):
    f = pdf()
    reader = StaticReader({f["name"]: {"pages": pages, "fields": fields, "hints": hints or {}}})
    pol = {**load_policy(), "require_documents_override": mode}
    ctx = make_ctx(gst or {GSTIN: gst_fixture()}, reader=reader, policy=pol)
    return ctx, f


FULL = [pg(1, "pan_card"), pg(2, "gst_certificate"), pg(3, "cancelled_cheque_or_bank_letter"), pg(4, "address_proof"), pg(5, "incorporation_or_name_change_certificate")]


# ---------- R26 ----------

def test_required_documents_missing_from_an_upload_are_flagged_to_the_vendor():
    ctx, f = pack_ctx([pg(1, "pan_card")], [fl("pan", PAN, 1, "pan_card")])
    cid, rid = submit(ctx, form(), [f])
    r = rule(ctx, rid, "R26")
    assert r["result"] == "flag" and r["owner"] == "vendor"
    for needed in ("GST registration certificate", "Cancelled cheque or bank confirmation letter", "Address proof", "Certificate of incorporation"):
        assert needed in r["reason"]
    assert "PAN card" not in r["found"]
    assert "We still need these documents" in str(case(ctx, cid).decision["message"])


def test_one_combined_pdf_with_every_document_passes_the_checklist():
    ctx, f = pack_ctx(FULL, [fl("pan", PAN, 1, "pan_card"), fl("gstin", GSTIN, 2, "gst_certificate")])
    cid, rid = submit(ctx, form(), [f])
    assert rule(ctx, rid, "R26")["result"] == "pass"


def test_checklist_is_information_only_for_a_typed_submission_without_documents():
    ctx, _ = pack_ctx([], [], mode="if_uploaded")
    cid, rid = submit(ctx, form(), [])
    c = rule(ctx, rid, "R26")               # nothing uploaded and not enforced: stated plainly, never a flag
    assert c["result"] == "info" and c["found"] == "No documents provided"
    assert case(ctx, cid).waiting_on == "finance"


def test_supporting_evidence_alone_does_not_trigger_the_full_pack_requirement():
    ctx, f = pack_ctx([pg(1, "stock_exchange_filing")], [], mode="if_uploaded")
    cid, rid = submit(ctx, form(), [f])
    assert rule(ctx, rid, "R26")["result"] == "info"


def test_msme_claim_requires_the_udyam_certificate():
    ctx, f = pack_ctx(FULL, [], mode="always")
    cid, rid = submit(ctx, form(msme=True, udyam_number="UDYAM-MH-01-1234567"), [f])
    assert "Udyam" in rule(ctx, rid, "R26")["reason"]


# ---------- R25 address ----------

def addr_ctx(proof_address):
    fields = [fl("address", "1 Test Road, Mumbai 400001", 2, "gst_certificate"), fl("address", proof_address, 4, "address_proof")]
    return pack_ctx(FULL, fields)


def test_address_proof_that_matches_the_gst_address_passes():
    ctx, f = addr_ctx("Flat 1, 1 Test Road, Mumbai - 400001")
    cid, rid = submit(ctx, form(), [f])
    assert rule(ctx, rid, "R25")["result"] == "pass"


def test_address_proof_for_a_different_place_is_flagged_to_procurement():
    ctx, f = addr_ctx("22 Hill Street, Pune 411026")
    cid, rid = submit(ctx, form(), [f])
    r = rule(ctx, rid, "R25")
    assert r["result"] == "flag" and r["owner"] == "procurement" and "411026" in r["reason"] and "400001" in r["reason"]


# ---------- R24 country signals ----------

def test_us_vendor_whose_documents_are_indian_is_flagged_even_though_the_typed_id_is_valid():
    us = dict(country="US", legal_name="LAKEVIEW LLC", tax_id="12-3456789", bank_account="123456789012", routing_code="021000021",
              contact_name="D", contact_email="d@x.example", contact_phone="+1 312 555 0100", **COMMERCIAL)
    ctx, f = pack_ctx([pg(1, "gst_certificate"), pg(2, "pan_card")], [], mode="off")
    cid, rid = submit(ctx, us, [f])
    r = rule(ctx, rid, "R24")
    assert r["result"] == "flag" and "Indian GST certificate" in r["reason"] and "United States" in r["reason"]


def test_a_phone_code_and_a_page_that_mentions_another_country_are_signals_too():
    us = dict(country="US", legal_name="LAKEVIEW LLC", tax_id="12-3456789", bank_account="123456789012", routing_code="021000021",
              contact_name="D", contact_email="d@x.example", contact_phone="+91 98765 43210", **COMMERCIAL)
    ctx, f = pack_ctx([pg(1, "tax_form_or_vat_certificate")], [], mode="off", hints={"1": ["IN"]})
    cid, rid = submit(ctx, us, [f])
    r = rule(ctx, rid, "R24")
    assert r["result"] == "flag" and "+91" in r["reason"] and "mentions India" in r["reason"]


def test_consistent_signals_pass():
    ctx, f = pack_ctx([pg(1, "pan_card")], [], mode="off", hints={"1": ["IN"]})
    cid, rid = submit(ctx, form(), [f])
    assert rule(ctx, rid, "R24")["result"] == "pass"


def test_a_typed_indian_id_that_contradicts_a_us_tax_form_says_what_each_one_looks_like():
    us = dict(country="US", legal_name="LAKEVIEW LLC", tax_id="27AAACK5521D1ZY", bank_account="123456789012", routing_code="021000021",
              contact_name="D", contact_email="d@x.example", contact_phone="+1 312 555 0100", **COMMERCIAL)
    ctx, f = pack_ctx([pg(1, "tax_form_or_vat_certificate")], [fl("tax_id", "12-3456789", 1, "tax_form_or_vat_certificate")], mode="off")
    cid, rid = submit(ctx, us, [f])
    r = rule(ctx, rid, "R05", "R05:tax_id")
    assert r["result"] == "flag" and "looks like an Indian GSTIN" in r["reason"] and "looks like a US EIN" in r["reason"]


# ---------- R27 / R28 ----------

def test_uncategorised_vendor_waits_on_procurement_and_categorising_opens_a_new_version():
    ctx = make_ctx()
    typed = {k: v for k, v in form().items() if k not in COMMERCIAL}
    cid, rid = submit(ctx, typed)
    assert rule(ctx, rid, "R27")["result"] == "flag" and rule(ctx, rid, "R28")["result"] == "flag"
    assert case(ctx, cid).waiting_on == "procurement"
    with pytest.raises(workflow.WorkflowError):
        workflow.set_commercial(ctx, cid, "arjun", dict(COMMERCIAL))               # only procurement categorises
    workflow.set_commercial(ctx, cid, "priya", dict(COMMERCIAL), background=False)
    c = case(ctx, cid)
    assert c.current_version == 2 and c.waiting_on == "finance"


@pytest.mark.parametrize("negotiated,configured,ok", [("Net 45", "45", True), ("45 days", "Net 45", True), ("Net 60", "30", False), ("as agreed", "30", False), ("45", "", False)])
def test_configured_payment_terms_must_equal_the_negotiated_terms_exactly(negotiated, configured, ok):
    ctx = make_ctx()
    cid, rid = submit(ctx, form(negotiated_terms=negotiated, system_terms=configured))
    assert (rule(ctx, rid, "R28")["result"] == "pass") is ok


def test_msme_payment_terms_over_45_days_are_refused():
    ctx = make_ctx()
    cid, rid = submit(ctx, form(msme=True, udyam_number="UDYAM-MH-01-1234567", negotiated_terms="60", system_terms="60"))
    assert rule(ctx, rid, "R28")["result"] == "flag" and "45" in rule(ctx, rid, "R28")["reason"]


def test_classification_and_terms_are_saved_on_the_vendor_record():
    ctx = make_ctx()
    ctx.sim = False
    cid, rid = submit(ctx, form())
    t = next(t for t in tasks(ctx, cid, "open") if t.key == "R16")
    workflow.resolve_task(ctx, t.id, "arjun", "confirmed", "called", "")
    workflow.approve_task(ctx, t.id, "neha")
    with Session(ctx.engine) as s:
        m = s.exec(__import__("sqlmodel").select(VendorMaster)).one()
    assert m.record["classification"] == {"vendor_type": "goods", "expense_category": "Raw materials", "department_owner": "Procurement"}
    assert m.record["payment_terms"]["matches_negotiated"] is True


# ---------- duplicates and vendor codes ----------

def add_master(s, code, pan, gstin, account):
    s.add(VendorMaster(vendor_code=code, pan=pan, legal_name=code, record={"gstins": [{"gstin": gstin}], "bank_accounts": [{"account": account, "ifsc": "X", "status": "active"}]}))
    s.commit()


def test_duplicate_search_covers_pan_gstin_and_bank_account():
    ctx = make_ctx()
    with Session(ctx.engine) as s:
        add_master(s, "VND-0001", "AAACB1234C", "27AAACB1234C1ZV", "111111111111")
        add_master(s, "VND-0002", "AAACQ9999Q", "27AAACQ9999Q1Z5", "222222222222")
        found = master.search_duplicates(s, "AAACB1234C", "", "222222222222")
    assert {k: x.vendor_code for k, x in found.items()} == {"PAN": "VND-0001", "bank account": "VND-0002"}


def test_identifiers_that_match_different_vendors_are_flagged_as_a_possible_duplicate():
    ctx = make_ctx()
    with Session(ctx.engine) as s:
        add_master(s, "VND-0001", PAN, GSTIN, "111111111111")
        add_master(s, "VND-0002", "AAACQ9999Q", "27AAACQ9999Q1Z5", "50100123456789")           # the account this submission uses
    cid, rid = submit(ctx, form())
    r = rule(ctx, rid, "R01", "R01:dup")
    assert r["result"] == "flag" and r["owner"] == "procurement" and "VND-0001" in r["found"] and "VND-0002" in r["found"]


def test_vendor_codes_are_never_reused_even_with_gaps_or_a_collision():
    ctx = make_ctx()
    with Session(ctx.engine) as s:
        add_master(s, "VND-0001", "A", "G1", "1")
        add_master(s, "VND-0005", "B", "G2", "2")
        assert master.next_code(s) == "VND-0006"                     # one above the highest ever issued, not a count
        clash = VendorMaster(vendor_code="VND-0005", pan="C", legal_name="C", record={})
        saved = master.save_unique(s, clash)                          # the database UNIQUE constraint refuses the repeat
        assert saved.vendor_code == "VND-0006"
        codes = [m.vendor_code for m in master.all_masters(s)]
        assert len(codes) == len(set(codes)) == 3


def test_rerunning_all_checks_opens_a_new_run_without_error():
    ctx, _ = pack_ctx([], [], mode="if_uploaded")
    cid, rid = submit(ctx, form(), [])
    new_rid = workflow.retry_case(ctx, cid, "priya", background=False)
    assert new_rid != rid
    assert case(ctx, cid).waiting_on == "finance"


def test_form_state_marks_an_unfilled_or_incomplete_typed_form():
    from vendorcheck.web.views import form_state
    assert form_state({"country": "IN", "contact_name": "Asha", "vendor_type": "goods"}) == {"state": "empty", "missing": []}
    assert form_state({}) == {"state": "empty", "missing": []}
    part = form_state({"legal_name": "X Ltd", "gstin": "27AAACX1234C1Z5"})
    assert part == {"state": "partial", "missing": ["Bank account"]}
    assert form_state({"legal_name": "X Ltd", "tax_id": "12-3456789", "iban": "DE89370400440532013000"}) is None


def test_duplicate_card_reads_the_intake_search_result():
    from vendorcheck.web.views import _duplicates

    def stage(found):
        return [{"key": "intake", "checks": [{"rule": "I2", "found": found}]}]

    same = _duplicates(stage("PAN → VND-0001 (Zoho Corp); GSTIN → VND-0001 (Zoho Corp); bank account → VND-0001 (Zoho Corp)"))
    assert same["conflict"] is False and same["vendors"][0]["keys"] == ["PAN", "GSTIN", "bank account"]
    split = _duplicates(stage("PAN → VND-0001 (A); bank account → VND-0002 (B)"))
    assert split["conflict"] is True and len(split["vendors"]) == 2
    assert _duplicates(stage("No existing vendor with this PAN, GSTIN or bank account")) is None
