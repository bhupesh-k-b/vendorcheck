from vendorcheck import checklist as ck


def dm(*pages):
    """doc_map with one file; pages = [(page_no, doc_type, foreign_holder)]"""
    return [{"sha": "a" * 64, "name": "pack.pdf", "pages": [{"page": n, "types": [{"doc_type": t, "note": "", "legible": True}], "fields": [], "foreign": f} for n, t, f in pages]}]


IN_CO = {"country": "IN", "legal_name": "Kaveri Precision Components Private Limited", "gstin": "27AAACK5521D1ZY", "pan": "AAACK5521D", "cin": "U29253MH2014PTC152873", "ifsc": "HDFC0000001"}


def by(rows):
    return {r.key: r for r in rows}


def test_everything_found_in_one_combined_pdf():
    rows = by(ck.build(IN_CO, dm((12, "pan_card", ""), (13, "gst_certificate", ""), (14, "cancelled_cheque_or_bank_letter", ""), (15, "address_proof", ""), (16, "incorporation_or_name_change_certificate", ""))))
    assert all(r.state == "found" for r in rows.values() if r.required) and rows["pan_card"].where == "pack.pdf p.12"
    assert rows["udyam_certificate"].state == "not_required"
    assert ck.missing(list(rows.values())) == []


def test_missing_documents_are_listed():
    rows = ck.build(IN_CO, dm((12, "pan_card", "")))
    assert {r.key for r in ck.missing(rows)} == {"gst_certificate", "bank_document", "address_proof", "incorporation"}


def test_msme_requires_a_udyam_certificate_only_when_claimed():
    assert "udyam_certificate" not in {r.key for r in ck.build(IN_CO, dm()) if r.required}
    assert "udyam_certificate" in {r.key for r in ck.build({**IN_CO, "msme": True}, dm()) if r.required}


def test_proprietor_does_not_need_a_certificate_of_incorporation():
    prop = {"country": "IN", "legal_name": "Mehta and Sons Traders", "gstin": "24AAAPM1234C1Z5", "pan": "AAAPM1234C"}
    assert "incorporation" in {r.key for r in ck.build(prop, dm()) if not r.required}


def test_a_bank_document_in_someone_elses_name_does_not_count():
    rows = by(ck.build(IN_CO, dm((9, "bank_details_form", "MUNITIONS INDIA LIMITED"))))
    assert rows["bank_document"].state == "other_party" and "MUNITIONS" in rows["bank_document"].where
    assert "bank_document" in {r.key for r in ck.missing(list(rows.values()))}


def test_foreign_vendor_needs_a_tax_document_and_a_bank_letter_not_indian_documents():
    us = {"country": "US", "legal_name": "Lakeview Industrial Supply LLC", "tax_id": "12-3456789"}
    keys = {r.key for r in ck.build(us, dm()) if r.required}
    assert keys == {"tax_form", "bank_document", "incorporation"}
    assert "pan_card" not in {r.key for r in ck.build(us, dm())}


def test_verify_links_are_attached():
    rows = by(ck.build(IN_CO, dm()))
    assert rows["pan_card"].link[1].startswith("https://eportal.incometax.gov.in") and rows["bank_document"].link[1].endswith("HDFC0000001")
    assert by(ck.build({"country": "DE", "legal_name": "X GmbH"}, dm()))["tax_form"].link[1].startswith("https://ec.europa.eu/taxation_customs/vies")
