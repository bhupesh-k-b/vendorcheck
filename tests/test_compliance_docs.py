"""Configurable compliance documents: documents added in Settings, built-in documents switched off, detection by your words, MSME off."""
from starlette.datastructures import FormData

from vendorcheck import checklist as ck
from vendorcheck import extract, policy


def doc_map(*pages):
    """pages: (page number, doc type) on one file."""
    return [{"sha": "x", "name": "pack.pdf", "pages": [{"page": n, "types": [{"doc_type": t, "note": "", "legible": True}], "fields": [], "foreign": ""} for n, t in pages]}]


INDIA_COMPANY = {"country": "IN", "gstin": "27AAACK5521D1ZY", "pan": "AAACK5521D", "cin": "U29253MH2014PTC152873", "legal_name": "Kaveri Precision Components Private Limited", "msme": True}


def pol(**docs):
    p = policy.load_policy()
    p["documents"] = {"enabled": docs.get("enabled", {}), "custom": docs.get("custom", [])}
    return p


AADHAAR = {"key": "aadhaar_card", "label": "Aadhaar card", "keywords": ["AADHAAR", "UNIQUE IDENTIFICATION AUTHORITY"], "need": 1, "applies": "india"}


def test_custom_document_words_match_a_page_even_when_spaces_are_dropped():
    assert extract.custom_types("Government of India  AADHAAR  Name RAJESH", [AADHAAR]) == ["aadhaar_card"]
    assert extract.custom_types("UNIQUEIDENTIFICATIONAUTHORITYOFINDIA", [AADHAAR]) == ["aadhaar_card"]
    assert extract.custom_types("Electricity bill", [AADHAAR]) == []
    two = {**AADHAAR, "keywords": ["AADHAAR", "DATE OF BIRTH"], "need": 2}
    assert extract.custom_types("AADHAAR only", [two]) == [] and extract.custom_types("AADHAAR Date of Birth", [two]) == ["aadhaar_card"]


def test_an_added_document_appears_in_the_checklist_as_missing_then_found():
    missing = ck.build(INDIA_COMPANY, doc_map((1, "pan_card")), pol(custom=[AADHAAR]))
    row = next(r for r in missing if r.key == "aadhaar_card")
    assert row.required and row.state == "missing" and row.label == "Aadhaar card" and "compliance policy" in row.why
    assert any(r.key == "aadhaar_card" for r in ck.missing(missing))                    # so the vendor is asked for it
    found = ck.build(INDIA_COMPANY, doc_map((1, "pan_card"), (7, "aadhaar_card")), pol(custom=[AADHAAR]))
    row = next(r for r in found if r.key == "aadhaar_card")
    assert row.state == "found" and row.where == "pack.pdf p.7"


def test_an_added_document_respects_who_it_applies_to():
    foreign = {"country": "US", "legal_name": "Lakeview Industrial Supply LLC"}
    assert not any(r.key == "aadhaar_card" for r in ck.build(foreign, [], pol(custom=[AADHAAR])))          # India only
    everyone = {**AADHAAR, "applies": "all"}
    assert any(r.key == "aadhaar_card" for r in ck.build(foreign, [], pol(custom=[everyone])))


def test_a_built_in_document_switched_off_is_not_asked_for():
    keys = [r.key for r in ck.build(INDIA_COMPANY, [], pol())]
    assert "udyam_certificate" in keys and "pan_card" in keys
    keys_off = [r.key for r in ck.build(INDIA_COMPANY, [], pol(enabled={"udyam_certificate": False}))]
    assert "udyam_certificate" not in keys_off and "pan_card" in keys_off


def test_the_settings_form_adds_removes_and_validates_documents():
    cur = policy.load_policy()
    form = FormData([("docs_form", "1"), ("doc__pan_card", "on"), ("doc__gst_certificate", "on"), ("doc__bank_document", "on"),       # udyam, address, incorporation, tax off
                     ("custom_label", "Aadhaar card"), ("custom_keywords", "aadhaar, unique identification authority"), ("custom_need", "1"), ("custom_applies", "india"),
                     ("custom_label", "Empty one"), ("custom_keywords", ""), ("custom_need", "1"), ("custom_applies", "all"),
                     ("custom_label", ""), ("custom_keywords", "ignored"), ("custom_need", "1"), ("custom_applies", "all")])
    errors = []
    docs = policy.documents_from_form(form, errors, cur.get("documents"))
    assert docs["enabled"]["pan_card"] is True and docs["enabled"]["udyam_certificate"] is False
    assert [d["key"] for d in docs["custom"]] == ["aadhaar_card"] and docs["custom"][0]["keywords"] == ["AADHAAR", "UNIQUE IDENTIFICATION AUTHORITY"]
    assert any("Empty one" in e for e in errors)                                         # a document with no words cannot be recognised: left out and reported


def test_a_form_without_the_documents_section_keeps_what_is_set():
    cur = {"enabled": {"udyam_certificate": False}, "custom": [AADHAAR]}
    assert policy.documents_from_form(FormData([("x", "1")]), [], cur) == cur


def test_two_documents_with_the_same_name_get_different_keys():
    form = FormData([("docs_form", "1"), ("custom_label", "ISO certificate"), ("custom_keywords", "ISO 9001"), ("custom_need", "1"), ("custom_applies", "all"),
                     ("custom_label", "ISO certificate"), ("custom_keywords", "ISO 14001"), ("custom_need", "1"), ("custom_applies", "all")])
    keys = [d["key"] for d in policy.documents_from_form(form, [], {})["custom"]]
    assert keys == ["iso_certificate", "iso_certificate_2"]
