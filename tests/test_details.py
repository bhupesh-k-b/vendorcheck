"""Configurable identity details: switch built-in details off, add your own (format-checked, required or optional)."""
from starlette.datastructures import FormData

from tests.conftest import GSTIN, form, gst_fixture, make_ctx
from tests.test_engine import case, rule, submit
from vendorcheck import policy
from vendorcheck.policy import load_policy

TAN = {"key": "tan", "label": "TAN", "format": "AAAA99999A", "required": True, "applies": "india"}


def ctx_with(**details):
    pol = {**load_policy(), "details": {"enabled": details.get("enabled", {}), "custom": details.get("custom", [])}}
    return make_ctx({GSTIN: gst_fixture()}, policy=pol)


def test_format_uses_letters_digits_and_wildcards_and_ignores_spaces_and_dashes():
    assert policy.format_ok("AAAA99999A", "PNEK12345E") and policy.format_ok("AAAA99999A", "pnek-12345 e")
    assert not policy.format_ok("AAAA99999A", "PNEK1234E") and not policy.format_ok("AAAA99999A", "PNEK123456")
    assert policy.format_ok("99999999999999", "1234 5678 9012 34") and policy.format_ok("**********", "AB12CD34EF")
    assert policy.format_ok("99/AA", "12/AB") and not policy.format_ok("99/AA", "12-AB")     # a literal character must be there (dashes are only ignored in the value when the format has none)


def test_switched_off_details_cover_their_fields():
    off = policy.disabled_fields({"details": {"enabled": {"gstin": False, "bank": False}}})
    assert {"gstin", "bank_account", "ifsc", "iban", "account_holder"} <= off and "pan" not in off and "cin" not in off
    assert policy.disabled_fields(load_policy()) == set()


def test_the_settings_form_parses_switches_and_added_details():
    form_ = FormData([("details_form", "1"), ("detail__gstin", "on"), ("detail__pan", "on"),                                   # cin and bank off
                      ("cdetail_label", "TAN"), ("cdetail_format", "aaaa99999a"), ("cdetail_required", "yes"), ("cdetail_applies", "india"),
                      ("cdetail_label", "Broken"), ("cdetail_format", "-- --"), ("cdetail_required", "no"), ("cdetail_applies", "all"),
                      ("cdetail_label", "FSSAI"), ("cdetail_format", "99999999999999"), ("cdetail_required", "no"), ("cdetail_applies", "all")])
    errors = []
    d = policy.details_from_form(form_, errors, {})
    assert d["enabled"] == {"gstin": True, "pan": True, "cin": False, "bank": False}
    assert [(x["key"], x["format"], x["required"], x["applies"]) for x in d["custom"]] == [("tan", "AAAA99999A", True, "india"), ("fssai", "99999999999999", False, "all")]
    assert any("Broken" in e for e in errors)
    assert policy.details_from_form(FormData([("x", "1")]), [], {"enabled": {"cin": False}, "custom": [TAN]}) == {"enabled": {"cin": False}, "custom": [TAN]}   # section absent: unchanged


def test_a_required_added_detail_that_is_missing_is_asked_of_the_vendor():
    ctx = ctx_with(custom=[TAN])
    cid, rid = submit(ctx, form())
    c = rule(ctx, rid, "R03")
    assert c["result"] == "flag" and "TAN" in c["reason"] and "x_tan" in c["vendor_fields"] and c["owner"] == "vendor"


def test_an_added_detail_in_the_wrong_format_is_flagged_and_a_good_one_passes():
    ctx = ctx_with(custom=[TAN])
    _, rid = submit(ctx, form(x_tan="PNEK12345E"))
    assert rule(ctx, rid, "X3")["result"] == "pass" and rule(ctx, rid, "R03")["result"] == "pass"
    ctx2 = ctx_with(custom=[TAN])
    _, rid2 = submit(ctx2, form(x_tan="PNEK1234"))
    c = rule(ctx2, rid2, "X3")
    assert c["result"] == "flag" and c["owner"] == "vendor" and "x_tan" in c["vendor_fields"] and "not in the expected format" in c["vendor_text"]


def test_an_optional_added_detail_can_be_left_blank_and_one_for_another_country_is_not_asked():
    optional = {**TAN, "required": False}
    ctx = ctx_with(custom=[optional])
    _, rid = submit(ctx, form())
    assert rule(ctx, rid, "R03")["result"] == "pass" and rule(ctx, rid, "X3") is None
    us_only = {**TAN, "applies": "foreign"}                           # an Indian vendor is not asked for a foreign-only detail
    ctx2 = ctx_with(custom=[us_only])
    _, rid2 = submit(ctx2, form())
    assert rule(ctx2, rid2, "R03")["result"] == "pass"


def test_switching_bank_off_means_no_bank_details_are_required_or_checked():
    bare = form(bank_account="", bank_account_confirm="", ifsc="")
    ctx_on = ctx_with()
    _, rid_on = submit(ctx_on, bare)
    assert rule(ctx_on, rid_on, "R03")["result"] == "flag"                      # control: bank details are required by default
    ctx = ctx_with(enabled={"bank": False})
    _, rid = submit(ctx, bare)
    assert rule(ctx, rid, "R03")["result"] == "pass" and rule(ctx, rid, "R09")["result"] == "skip"
    ctx_typed = ctx_with(enabled={"bank": False})                              # bank values that ARE typed are ignored too
    _, rid_t = submit(ctx_typed, form())
    assert rule(ctx_typed, rid_t, "R09")["result"] == "skip"


def test_switching_gstin_off_ignores_it_and_skips_the_registry():
    ctx = ctx_with(enabled={"gstin": False})
    cid, rid = submit(ctx, form())
    assert rule(ctx, rid, "R06")["result"] == "skip" and rule(ctx, rid, "R11")["result"] == "skip"
    assert ctx.gst.calls == []                                                 # no registry call was made


def test_a_switched_off_detail_has_no_row_in_the_evidence_summary_and_an_added_one_does():
    from sqlmodel import Session

    from vendorcheck.workflow import latest_version

    def labels(ctx, cid):
        with Session(ctx.engine) as s:
            return [r["label"] for r in latest_version(s, cid).profile["table"]]
    on = ctx_with(custom=[TAN])
    cid, _ = submit(on, form(x_tan="PNEK12345E"))
    assert "CIN" in labels(on, cid) and "TAN" in labels(on, cid)
    off = ctx_with(enabled={"cin": False, "bank": False})
    cid2, _ = submit(off, form())
    got = labels(off, cid2)
    assert "CIN" not in got and "IFSC" not in got and "Account holder" not in got and "PAN" in got
