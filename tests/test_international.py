"""Vendors outside India: identify the country from the ID, check shape/checksum only, never call Indian sources."""
from sqlmodel import Session, select

from tests.conftest import COMMERCIAL, GSTIN, PAN, make_ctx
from tests.test_engine import case, rule, submit, tasks
from vendorcheck import workflow
from vendorcheck.models import VendorMaster

NAME = "LAKEVIEW INDUSTRIAL SUPPLY LLC"


def us(**over):
    d = dict(country="US", legal_name=NAME, tax_id="12-3456789", bank_account="123456789012", routing_code="021000021", swift="",
             contact_name="Dana Cole", contact_email="dana@lakeview.example", contact_phone="+1 312 555 0100", **COMMERCIAL)
    d.update(over)
    return d


def de(**over):
    d = dict(country="DE", legal_name="Rheinland Werkzeug GmbH", tax_id="DE123456789", iban="DE89370400440532013000", swift="COBADEFFXXX",
             contact_name="Anna Weber", contact_email="anna@rheinland.example", contact_phone="+49 30 1234567", **COMMERCIAL)
    d.update(over)
    return d


def test_the_users_case_us_vendor_with_an_indian_gstin_is_flagged_and_no_indian_source_is_called():
    ctx = make_ctx()
    cid, rid = submit(ctx, us(tax_id="", gstin=GSTIN, pan=PAN))
    r = rule(ctx, rid, "R23")
    assert r["result"] == "flag" and r["owner"] == "vendor"
    assert "an Indian GSTIN" in r["reason"] and "United States" in r["reason"]
    assert ctx.gst.calls == []                                           # no GST credit spent on a US vendor
    assert rule(ctx, rid, "R11")["result"] == "skip" and "Not applicable" in rule(ctx, rid, "R11")["reason"]
    assert rule(ctx, rid, "R06")["result"] == "skip"
    c = case(ctx, cid)
    assert c.status == "pending" and c.waiting_on == "vendor"
    text = str(c.decision["message"])
    assert "looks like an Indian GSTIN" in text and "United States" in text and GSTIN not in text     # masked for the vendor


def test_a_valid_us_ein_passes_the_format_check_but_is_never_called_verified():
    ctx = make_ctx()
    cid, rid = submit(ctx, us())
    assert rule(ctx, rid, "R23")["result"] == "pass" and "format and check-digit test only" in rule(ctx, rid, "R23")["reason"]
    assert rule(ctx, rid, "R09")["result"] == "pass"
    assert ctx.gst.calls == []
    v = next(c for e in __import__("tests.test_engine", fromlist=["checks"]).checks(ctx, rid).values() for c in e.checks if c["key"] == "R23v")
    assert v["result"] == "wait" and v["owner"] == "procurement" and v["assist"] == "taxid"
    c = case(ctx, cid)
    assert c.status == "pending" and c.waiting_on == "procurement"


def test_foreign_vendor_reaches_approved_only_after_a_person_checked_the_register_and_finance_confirmed_the_bank():
    ctx = make_ctx()
    cid, rid = submit(ctx, us())
    shot = {"sha256": "b" * 64, "name": "irs.png"}
    workflow.save_assisted(ctx, cid, "taxid", "12-3456789", {"tax_id": "12-3456789", "legal_name": NAME, "status": "Valid"}, shot, "priya")
    t = next(t for t in tasks(ctx, cid) if t.key == "R23v")
    workflow.approve_task(ctx, t.id, "neha", background=False)
    bank = next(t for t in tasks(ctx, cid, "open") if t.key == "R16")
    workflow.resolve_task(ctx, bank.id, "arjun", "confirmed", "called the bank", "")
    workflow.approve_task(ctx, bank.id, "neha", background=False)
    c = case(ctx, cid)
    assert c.status == "approved"
    with Session(ctx.engine) as s:
        m = s.exec(select(VendorMaster)).one()
    assert m.pan == "US:123456789" and m.record["country"] == "US" and m.record["tax_id"]["value"] == "123456789" and "pan" not in m.record
    assert ctx.gst.calls == []


def test_register_says_not_found_goes_back_to_the_vendor():
    ctx = make_ctx()
    cid, rid = submit(ctx, us())
    workflow.save_assisted(ctx, cid, "taxid", "12-3456789", {"tax_id": "12-3456789", "status": "Not found"}, {"sha256": "c" * 64, "name": "x.png"}, "priya")
    t = next(t for t in tasks(ctx, cid) if t.key == "R23v")
    workflow.approve_task(ctx, t.id, "neha", background=False)
    assert any(i["key"] == "R23v" and i["owner"] == "vendor" for i in case(ctx, cid).decision["open_items"])


def test_eu_vendor_with_an_iban_from_another_country_is_flagged():
    ctx = make_ctx()
    cid, rid = submit(ctx, de(iban="FR1420041010050500013M02606"))
    r = rule(ctx, rid, "R09")
    assert r["result"] == "flag" and "FR" in r["reason"] and "Germany" in r["reason"]


def test_eu_vendor_with_a_tax_id_from_another_country_is_flagged():
    ctx = make_ctx()
    cid, rid = submit(ctx, de(tax_id="FR12345678901"))
    assert "a French VAT number" in rule(ctx, rid, "R23")["reason"]


def test_a_typing_error_in_a_us_routing_number_is_caught_by_its_checksum():
    ctx = make_ctx()
    cid, rid = submit(ctx, us(routing_code="021000022"))
    assert rule(ctx, rid, "R09")["result"] == "flag" and "check digit" in rule(ctx, rid, "R09")["reason"]


def test_an_indian_vendor_who_gives_a_us_ein_is_told_so():
    ctx = make_ctx()
    cid, rid = submit(ctx, dict(country="IN", legal_name="Test Traders", tax_id="12-3456789", bank_account="50100123456789", ifsc="HDFC0000001",
                                contact_name="A", contact_email="a@b.example"))
    assert "a US EIN" in rule(ctx, rid, "R23")["reason"] and ctx.gst.calls == []


def test_country_is_inferred_for_indian_ids_and_asked_for_when_it_cannot_be():
    ctx = make_ctx()
    from tests.conftest import form
    cid, rid = submit(ctx, form())                                              # no country typed, Indian IDs
    assert rule(ctx, rid, "R23")["result"] == "pass" and "inferred" in rule(ctx, rid, "R23")["reason"]
    cid2, rid2 = submit(ctx, dict(legal_name="Mystery Ltd", tax_id="123456789", bank_account="123456789012", contact_name="A", contact_email="a@b.example"))
    r03 = rule(ctx, rid2, "R03")
    assert r03["result"] == "flag" and "country" in r03["reason"]               # nine digits alone are ambiguous: never guessed


def test_vendor_corrects_the_country_and_version_two_passes_the_tax_id_check():
    ctx = make_ctx()
    cid, rid = submit(ctx, us(tax_id="", gstin=GSTIN, pan=PAN))
    from vendorcheck import pipeline
    vid = workflow.new_version(ctx, cid, {"tax_id": "12-3456789"}, [], "vendor")
    # the wrong Indian ID is dropped from the new version by the vendor's correction: simulate by clearing it
    with Session(ctx.engine) as s:
        from vendorcheck.models import Version
        ver = s.get(Version, vid)
        ver.declared = {k: val for k, val in ver.declared.items() if k not in ("gstin", "pan")}
        s.add(ver)
        s.commit()
    rid2 = pipeline.start_run(ctx, cid, vid, "vendor correction", background=False)
    assert rule(ctx, rid2, "R23")["result"] == "pass" and ctx.gst.calls == []
