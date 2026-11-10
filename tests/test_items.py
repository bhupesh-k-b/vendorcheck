"""Extra compliance items: one item can carry a number and a document; they show in the checklist, the consistency table, the case summary and the dashboard."""
import pytest
from sqlmodel import Session
from starlette.datastructures import FormData

from tests.conftest import GSTIN, form, gst_fixture, make_ctx
from tests.test_engine import submit
from tests.test_vendor_setup import fl, pdf, pg
from vendorcheck import config, extract, policy, storage
from vendorcheck.policy import load_policy
from vendorcheck.reader import StaticReader
from vendorcheck.web import views
from vendorcheck.workflow import latest_version

FSSAI_FORM = [("items_form", "1"), ("item_label", "FSSAI licence"), ("item_format", "99999999999999"), ("item_words", "fssai, food safety and standards authority"),
              ("item_need", "1"), ("item_required", "yes"), ("item_applies", "india"), ("item_enabled", "on")]


@pytest.fixture(autouse=True)
def tmp_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")


def policy_with_fssai(**over):
    pol = load_policy()
    docs, dets = policy.items_from_form(FormData(FSSAI_FORM), [])
    pol["documents"] = {"enabled": {}, "custom": docs}
    pol["details"] = {"enabled": {}, "custom": dets}
    pol.update(over)
    return pol


def test_one_item_with_a_number_and_words_becomes_a_document_and_a_detail_sharing_a_key():
    docs, dets = policy.items_from_form(FormData(FSSAI_FORM), [])
    assert [(d["key"], d["keywords"], d["required"]) for d in docs] == [("fssai_licence", ["FSSAI", "FOOD SAFETY AND STANDARDS AUTHORITY"], True)]
    assert [(d["key"], d["format"], d["label"], d["item"]) for d in dets] == [("fssai_licence", "99999999999999", "FSSAI licence number", "FSSAI licence")]


def test_items_only_the_number_or_only_the_document_and_nothing_at_all():
    form_ = FormData([("items_form", "1"),
                      ("item_label", "D-U-N-S"), ("item_format", "999999999"), ("item_words", ""), ("item_need", "1"), ("item_required", "no"), ("item_applies", "all"), ("item_enabled", "on"),
                      ("item_label", "Aadhaar card"), ("item_format", ""), ("item_words", "AADHAAR"), ("item_need", "1"), ("item_required", "yes"), ("item_applies", "india"), ("item_enabled", "on"),
                      ("item_label", "Empty"), ("item_format", ""), ("item_words", ""), ("item_need", "1"), ("item_required", "yes"), ("item_applies", "all"), ("item_enabled", "on")])
    errors = []
    docs, dets = policy.items_from_form(form_, errors)
    assert [d["key"] for d in dets] == ["d_u_n_s"] and dets[0]["required"] is False and [d["key"] for d in docs] == ["aadhaar_card"]
    assert any("Empty" in e for e in errors)


def test_the_settings_screen_gets_the_items_back_merged_and_an_off_item_does_not_count():
    pol = policy_with_fssai()
    ui = policy.items_for_ui(pol)
    assert ui == [{"label": "FSSAI licence", "format": "99999999999999", "words": "FSSAI, FOOD SAFETY AND STANDARDS AUTHORITY", "need": 1, "required": "yes", "applies": "india", "enabled": True}]
    off = FormData([*FSSAI_FORM[:-1], ("item_enabled", "off")])
    docs, dets = policy.items_from_form(off, [])
    pol["documents"]["custom"], pol["details"]["custom"] = docs, dets
    assert policy.custom_docs(pol) == [] and policy.custom_details(pol) == []             # kept in Settings, ignored by every run
    assert policy.items_for_ui(pol)[0]["enabled"] is False


def test_the_number_is_found_next_to_its_words_on_a_recognised_page():
    items = [{"key": "fssai_licence", "format": "99999999999999", "keywords": ["FSSAI"]}]
    got = extract.custom_values("FSSAI LICENCE  Licence Number 1234 5678 9012 34  Name of Operator X", items, ["fssai_licence"])
    assert got and got[0]["field"] == "x_fssai_licence" and got[0]["value"] == "12345678901234" and got[0]["doc_type"] == "fssai_licence"
    assert extract.custom_values("Licence 1234", items, ["fssai_licence"]) == []                  # not the right shape
    assert extract.custom_values("12345678901234", items, ["pan_card"]) == []                      # its document was not recognised on this page


def _run(pol, typed, scripted_pages=None, scripted_fields=None):
    f = pdf()
    reader = StaticReader({f["name"]: {"pages": scripted_pages or [], "fields": scripted_fields or [], "hints": {}}})
    ctx = make_ctx({GSTIN: gst_fixture()}, reader=reader, policy=pol)
    cid, rid = submit(ctx, typed, [f] if scripted_pages is not None else [])
    with Session(ctx.engine) as s:
        return ctx, cid, latest_version(s, cid).profile


def test_item_found_everywhere_shows_in_the_checklist_summary_and_consistency_table():
    pages = [pg(1, "pan_card"), pg(2, "fssai_licence")]
    fields = [fl("pan", "AAACB1234C", 1, "pan_card"), {"field": "x_fssai_licence", "value": "12345678901234", "page": 2, "doc_type": "fssai_licence", "snippet": "12345678901234"}]
    ctx, cid, prof = _run(policy_with_fssai(), form(x_fssai_licence="12345678901234"), pages, fields)
    row = next(r for r in prof["checklist"] if r["key"] == "fssai_licence")
    assert row["state"] == "found" and row["label"] == "FSSAI licence" and "p.2" in row["where"]
    item = prof["compliance"][0]
    assert item["doc"] == "found" and item["number"] == "ok" and item["value"] == "12345678901234" and item["doc_value"] == "12345678901234"
    assert ("x_fssai_licence", "FSSAI licence number") in [tuple(f) for f in prof["matrix"]["fields"]]
    cells = {r["kind"]: r["cells"]["x_fssai_licence"]["state"] for r in prof["matrix"]["rows"] if "x_fssai_licence" in r["cells"]}
    assert cells["typed"] == "ok" and cells["fssai_licence"] == "ok"
    ev = next(r for r in prof["table"] if r["label"] == "FSSAI licence number")
    assert ev["declared"] == ev["document"] == "12345678901234" and ev["result"] == "match"


def test_item_missing_is_marked_in_the_summary_the_consistency_table_and_the_dashboard():
    pages = [pg(1, "pan_card")]
    ctx, cid, prof = _run(policy_with_fssai(), form(), pages, [fl("pan", "AAACB1234C", 1, "pan_card")])
    item = prof["compliance"][0]
    assert item["doc"] == "missing" and item["number"] == "missing"
    absent = [r for r in prof["matrix"]["rows"] if r.get("absent")]
    assert absent and absent[0]["label"] == "FSSAI licence" and absent[0]["ref"] == "Not provided"
    assert absent[0]["cells"]["x_fssai_licence"]["state"] == "missing"
    with Session(ctx.engine) as s:
        rows = views.case_rows(s)
    assert rows[0]["missing_items"] == ["FSSAI licence"]


def test_a_missing_item_never_breaks_a_run_even_when_no_holder_name_or_other_column_exists():
    from tests.test_engine import checks
    f = pdf()
    reader = StaticReader({f["name"]: {"pages": [pg(1, "pan_card")], "fields": [fl("pan", "AAACB1234C", 1, "pan_card")], "hints": {}}})
    ctx = make_ctx({GSTIN: gst_fixture()}, reader=reader, policy=policy_with_fssai())
    cid, rid = submit(ctx, form(bank_account="", bank_account_confirm="", ifsc=""), [f])         # no bank details anywhere: no holder-name column in the matrix
    evs = checks(ctx, rid)
    assert all(e.status in ("passed", "flagged") and e.ended_at for e in evs.values()), {k: e.status for k, e in evs.items()}
    with Session(ctx.engine) as s:
        prof = latest_version(s, cid).profile
    assert any(r.get("absent") for r in prof["matrix"]["rows"])                                  # the "Not provided" row is there and complete
    assert all(set(r["cells"]) == set(prof["matrix"]["rows"][0]["cells"]) for r in prof["matrix"]["rows"])


def test_a_number_printed_on_the_document_counts_when_the_form_did_not_give_it():
    pages = [pg(1, "fssai_licence")]
    fields = [{"field": "x_fssai_licence", "value": "12345678901234", "page": 1, "doc_type": "fssai_licence", "snippet": "1"}]
    ctx, cid, prof = _run(policy_with_fssai(), form(), pages, fields)                       # nothing typed for the FSSAI number
    item = prof["compliance"][0]
    assert item["doc"] == "found" and item["number"] == "ok" and item["number_src"] == "document" and item["value"] == "12345678901234"
    from tests.test_engine import rule
    with Session(ctx.engine) as s:
        from sqlmodel import select
        from vendorcheck.models import Run
        rid = s.exec(select(Run).where(Run.case_id == cid)).all()[-1].id
    r03 = rule(ctx, rid, "R03")
    assert r03["result"] == "pass" or "FSSAI" not in r03["reason"]                           # the vendor is not asked for what the document already shows
    assert "Read from the document" in rule(ctx, rid, "X3")["reason"]


RECEIPT = """GovernmentofSomeState
FoodSafety andStandardsAuthorityof India
Receipt
ReferenceNo:  30230420113301206  Date:  20-04-2023
NameofCompany/  acmetraders  CategoryofLicense:  Registration[State][Renewal of
Organization:  Registration]
PremisesAddress:  villageOneTwo,Gabhana
Tahsil,Aligarh,,Some State,
202136
Kind of Business:  Trade/Retail-Retailer
Mode of Payment:  Razorpay
Transaction No.:  1424307003565372
"""


def test_everything_a_document_states_is_read_even_when_the_reader_drops_spaces():
    got = extract.document_details(RECEIPT)
    assert got["legal_name"] == "acmetraders"
    assert got["address"] == "villageOneTwo,Gabhana Tahsil,Aligarh,,Some State, 202136"
    assert got["kind_of_business"] == "Trade/Retail-Retailer" and got["reference_no"] == "30230420113301206" and got["document_date"] == "20-04-2023"
    licence = extract.document_details("FSSAI LICENCE\nLicence Number: 12345678901234\nName of Operator: MEHTA AND SONS TRADERS\nPremises: Plot 7, GIDC Vatva, Ahmedabad\nValid Upto: 31 Dec 2027\n")
    assert licence["legal_name"] == "MEHTA AND SONS TRADERS" and licence["address"] == "Plot 7, GIDC Vatva, Ahmedabad" and licence["valid_until"] == "31 Dec 2027"
    assert extract.document_details("Nothing labelled here") == {}


def _fssai_run(doc_name, typed_name="Blue Heron Trading Private Limited"):
    pages = [pg(1, "fssai_licence")]
    fields = [{"field": "legal_name", "value": doc_name, "page": 1, "doc_type": "fssai_licence", "snippet": doc_name},
              {"field": "address", "value": "Plot 7 GIDC Vatva Ahmedabad Gujarat 382445", "page": 1, "doc_type": "fssai_licence", "snippet": "a"},
              {"field": "kind_of_business", "value": "Wholesale trading", "page": 1, "doc_type": "fssai_licence", "snippet": "k"},
              {"field": "x_fssai_licence", "value": "12345678901234", "page": 1, "doc_type": "fssai_licence", "snippet": "n"}]
    return _run(policy_with_fssai(), form(legal_name=typed_name, x_fssai_licence="12345678901234"), pages, fields)


def test_a_name_on_the_document_that_does_not_match_the_case_is_flagged_everywhere():
    ctx, cid, prof = _fssai_run("ACME TRADERS")
    item = prof["compliance"][0]
    assert item["name_check"] == "differs" and {"label": "Name", "value": "ACME TRADERS"} in item["details"]
    assert {"label": "Kind of business", "value": "Wholesale trading"} in item["details"]
    row = next(r for r in prof["matrix"]["rows"] if r["kind"] == "fssai_licence")
    assert row["cells"]["legal_name"]["state"] == "bad" and "ACME TRADERS" in row["cells"]["legal_name"]["reason"]
    assert "legal_name" in prof["matrix"]["conflicts"]                                    # so procurement is asked to review the difference
    with Session(ctx.engine) as s:
        assert views.case_rows(s)[0]["missing_items"] == ["FSSAI licence (name differs)"]


def test_a_matching_name_on_the_document_is_confirmed():
    _, _, prof = _fssai_run("BLUE HERON TRADING PRIVATE LIMITED")
    assert prof["compliance"][0]["name_check"] == "ok"
    row = next(r for r in prof["matrix"]["rows"] if r["kind"] == "fssai_licence")
    assert row["cells"]["legal_name"]["state"] == "ok" and row["cells"]["x_fssai_licence"]["state"] == "ok"


def test_an_address_on_the_document_is_checked_against_the_typed_address():
    pages = [pg(1, "fssai_licence")]
    doc_fields = [{"field": "address", "value": "Plot 7 GIDC Vatva Ahmedabad Gujarat 382445", "page": 1, "doc_type": "fssai_licence", "snippet": "a"},
                  {"field": "x_fssai_licence", "value": "12345678901234", "page": 1, "doc_type": "fssai_licence", "snippet": "n"}]
    base = dict(gstin="", pan="", x_fssai_licence="12345678901234")                              # no GSTIN: no registry address to compare with either
    _, _, alone = _run(policy_with_fssai(), form(**base), pages, doc_fields)
    assert alone["compliance"][0]["address_check"] == "none"                                      # nothing else shows an address: not "agreeing", just nothing to compare
    assert next(r for r in alone["matrix"]["rows"] if r["kind"] == "fssai_licence")["cells"]["address"]["state"] == "alone"
    _, _, same = _run(policy_with_fssai(), form(**base, address="Plot 7, GIDC Vatva, Ahmedabad, Gujarat - 382445"), pages, doc_fields)
    assert same["compliance"][0]["address_check"] == "ok"
    assert next(r for r in same["matrix"]["rows"] if r["kind"] == "fssai_licence")["cells"]["address"]["state"] == "ok"
    ctx2, _, other = _run(policy_with_fssai(), form(**base, address="12 Park Street, Kolkata, West Bengal - 700016"), pages, doc_fields)
    assert other["compliance"][0]["address_check"] == "differs"
    assert "address" in other["matrix"]["conflicts"]                                              # flagged for review, with both addresses in the reason
    with Session(ctx2.engine) as s:
        assert views.case_rows(s)[0]["missing_items"] == ["FSSAI licence (address differs)"]


def test_a_value_only_one_source_shows_is_marked_alone_and_never_counted_as_agreement():
    from vendorcheck.matrix import Source, build
    one = build([Source("typed", "", {"legal_name": "ACME LTD"}), Source("fssai_licence", "f.pdf", {"address": "1 Main Road 400001"})],
                extra=[], doc_fields={"fssai_licence": ""})
    cell = next(r for r in one["rows"] if r["kind"] == "fssai_licence")["cells"]["address"]
    assert cell["state"] == "alone" and "nothing to compare" in cell["reason"]
    two = build([Source("typed", "", {"legal_name": "ACME LTD", "address": "1 Main Road 400001"}), Source("fssai_licence", "f.pdf", {"address": "1 Main Road 400001"})],
                extra=[], doc_fields={"fssai_licence": ""})
    assert next(r for r in two["rows"] if r["kind"] == "fssai_licence")["cells"]["address"]["state"] == "ok"
    assert one["cells_checked"] < two["cells_checked"]                                         # a lone value adds nothing to the score


def test_a_document_that_states_no_name_is_not_marked_as_missing_one():
    pages = [pg(1, "fssai_licence")]
    fields = [{"field": "x_fssai_licence", "value": "12345678901234", "page": 1, "doc_type": "fssai_licence", "snippet": "n"}]
    _, _, prof = _run(policy_with_fssai(), form(x_fssai_licence="12345678901234"), pages, fields)
    row = next(r for r in prof["matrix"]["rows"] if r["kind"] == "fssai_licence")
    assert row["cells"]["legal_name"]["state"] == "na" and row["cells"]["address"]["state"] == "na"      # nothing read, nothing counted against the score
    assert prof["compliance"][0]["name_check"] == ""


def test_a_page_that_is_your_document_is_not_also_a_generic_certificate():
    pages = [pg(1, "fssai_licence"), pg(1, "other_certificate")]                  # the reader (or its AI step) also called the page a generic certificate
    fields = [{"field": "x_fssai_licence", "value": "12345678901234", "page": 1, "doc_type": "fssai_licence", "snippet": "1"},
              {"field": "legal_name", "value": "MEHTA AND SONS TRADERS", "page": 1, "doc_type": "other_certificate", "snippet": "M"}]
    _, _, prof = _run(policy_with_fssai(), form(x_fssai_licence="12345678901234"), pages, fields)
    kinds = {r["kind"] for r in prof["matrix"]["rows"]}
    assert "fssai_licence" in kinds and "other_certificate" not in kinds
    assert [t["doc_type"] for f in prof["doc_map"] for p in f["pages"] for t in p["types"]] == ["fssai_licence"]


def test_a_mismatch_between_the_typed_number_and_the_document_is_visible():
    pages = [pg(1, "fssai_licence")]
    fields = [{"field": "x_fssai_licence", "value": "99999999999999", "page": 1, "doc_type": "fssai_licence", "snippet": "9"}]
    _, _, prof = _run(policy_with_fssai(), form(x_fssai_licence="12345678901234"), pages, fields)
    ev = next(r for r in prof["table"] if r["label"] == "FSSAI licence number")
    assert ev["result"] == "mismatch"
    states = {r["kind"]: r["cells"]["x_fssai_licence"]["state"] for r in prof["matrix"]["rows"] if "x_fssai_licence" in r["cells"]}
    assert states["typed"] == "bad" or states["fssai_licence"] == "bad"                          # the two sources disagree
