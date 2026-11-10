from vendorcheck.matrix import Source, build

NAME = "KAVERI PRECISION COMPONENTS PRIVATE LIMITED"


def pack(cheque_account="50100123456789", form_account="50100123456789", typed_account="50100123456789"):
    return [
        Source("typed", "", {"legal_name": NAME, "bank_account": typed_account, "ifsc": "HDFC0000001"}),
        Source("vendor_registration_form", "form.pdf p.1-3", {"legal_name": NAME, "bank_account": form_account, "ifsc": "HDFC0000001"}),
        Source("cancelled_cheque_or_bank_letter", "cheque.png", {"bank_account": cheque_account, "ifsc": "HDFC0000001", "account_holder": NAME}),
        Source("pan_card", "pan.png", {"pan": "AAACK1234C", "legal_name": NAME}),
    ]


def cell(m, kind, f):
    return next(r for r in m["rows"] if r["kind"] == kind)["cells"][f]


def test_all_consistent_scores_high_and_flags_nothing():
    m = build(pack())
    # nothing disagrees; the score is below 100 only because the forms in this pack omit PAN/GSTIN/CIN (shown as O)
    assert m["conflicts"] == {} and 50 <= m["score"] < 100
    assert cell(m, "cancelled_cheque_or_bank_letter", "bank_account")["state"] == "ok"


def test_account_number_differs_on_the_cheque_is_flagged_on_the_odd_one_out():
    m = build(pack(cheque_account="50100123450000"))
    assert cell(m, "cancelled_cheque_or_bank_letter", "bank_account")["state"] == "bad"
    assert cell(m, "vendor_registration_form", "bank_account")["state"] == "ok"
    assert cell(m, "typed", "bank_account")["state"] == "ok"
    reason = cell(m, "cancelled_cheque_or_bank_letter", "bank_account")["reason"]
    assert "Cancelled cheque" in reason and "0000" in reason and "6789" in reason     # names both values (masked)
    assert m["score"] < build(pack())["score"]


def test_two_against_one_in_the_user_example():
    # platform form 2345, registration form 1234, cheque 1234 -> the platform form is the odd one out
    m = build(pack(cheque_account="111111111234", form_account="111111111234", typed_account="111111112345"))
    assert cell(m, "typed", "bank_account")["state"] == "bad"
    assert cell(m, "vendor_registration_form", "bank_account")["state"] == "ok"


def test_missing_is_O_and_not_applicable_is_blank():
    srcs = pack()
    del srcs[2].values["ifsc"]
    m = build(srcs)
    assert cell(m, "cancelled_cheque_or_bank_letter", "ifsc")["state"] == "missing"
    assert cell(m, "pan_card", "bank_account")["state"] == "na"


def test_a_tie_marks_every_disagreeing_source_bad():
    m = build([Source("typed", "", {"bank_account": "1111111111"}), Source("cancelled_cheque_or_bank_letter", "c.png", {"bank_account": "2222222222"})])
    assert cell(m, "typed", "bank_account")["state"] == "bad" and cell(m, "cancelled_cheque_or_bank_letter", "bank_account")["state"] == "bad"


def test_government_record_breaks_a_tie():
    gov = Source("government", "GST live", {"gstin": "27AAACK1234C1Z5", "legal_name": NAME}, authority=True)
    m = build([Source("typed", "", {"legal_name": NAME}), Source("pan_card", "p.png", {"legal_name": "SOMEONE ELSE LIMITED"}), gov])
    assert cell(m, "pan_card", "legal_name")["state"] == "bad" and cell(m, "typed", "legal_name")["state"] == "ok"


def test_unclear_values_never_count_as_agreeing():
    s = pack()
    s[2].unclear.add("bank_account")
    assert cell(build(s), "cancelled_cheque_or_bank_letter", "bank_account")["state"] == "unclear"


def test_typed_account_holder_is_compared_with_the_bank_document_and_the_legal_name():
    ok = build([Source("typed", "", {"legal_name": NAME, "account_holder": NAME}),
                Source("cancelled_cheque_or_bank_letter", "c.png", {"bank_account": "50100123456789", "account_holder": NAME})])
    assert cell(ok, "typed", "account_holder")["state"] == "ok" and cell(ok, "cancelled_cheque_or_bank_letter", "account_holder")["state"] == "ok"
    bad = build([Source("typed", "", {"legal_name": NAME, "account_holder": "RAVI KULKARNI"}),
                 Source("cancelled_cheque_or_bank_letter", "c.png", {"bank_account": "50100123456789", "account_holder": NAME})])
    assert cell(bad, "typed", "account_holder")["state"] == "bad" and "account_holder" in bad["conflicts"]


def test_a_blank_typed_holder_is_neutral_not_a_gap():
    m = build([Source("typed", "", {"legal_name": NAME, "bank_account": "50100123456789"}),
               Source("cancelled_cheque_or_bank_letter", "c.png", {"bank_account": "50100123456789", "account_holder": NAME})])
    assert cell(m, "typed", "account_holder")["state"] == "na"


def test_a_companys_own_unit_account_matches_the_company():
    from vendorcheck.matrix import unit_of
    assert unit_of("MUNITIONS INDIA LIMITED O F KHAMARIA", "MUNITIONS INDIA LIMITED")
    assert not unit_of("KAVERI PRECISION COMPONENTS PRIVATE LIMITED", "RAVI KULKARNI")
    assert unit_of("MUNITIONSINDIALIMITEDOF KHAMARIA", "Munitions India Limited")      # the reader drops spaces
    assert not unit_of("TATA STEEL", "TATA MOTORS")           # a short shared prefix is not enough
    assert not unit_of("TATA STEEL", "TATA STEEL")            # equal names are handled by the normal match, not this rule
    m = build([Source("typed", "", {"legal_name": "MUNITIONS INDIA LIMITED"}),
               Source("bank_details_form", "f.pdf", {"bank_account": "40436892598", "account_holder": "MUNITIONS INDIA LIMITED O F KHAMARIA"})])
    assert cell(m, "bank_details_form", "account_holder")["state"] == "ok"


def test_a_proprietors_personal_pan_card_is_expected_not_missing():
    m = build([Source("typed", "", {"legal_name": NAME, "pan": "AAAPM4521K"}),
               Source("pan_card", "pan.pdf", {"pan": "AAAPM4521K"}, proprietor="RAJESH MEHTA")])
    c = cell(m, "pan_card", "legal_name")
    assert c["state"] == "proprietor" and c["value"] == "RAJESH MEHTA"
    assert m["conflicts"] == {}


def test_missing_required_documents_pull_the_score_down_and_out_of_strong():
    from vendorcheck.matrix import apply_coverage
    m = build([Source("typed", "", {"legal_name": NAME, "pan": "AAACK1234C"}), Source("pan_card", "p", {"pan": "AAACK1234C", "legal_name": NAME})])
    assert m["score"] == 100 and m["band"] == "strong"
    apply_coverage(m, 3, 6, ["Cancelled cheque", "Address proof", "PAN card"])
    assert m["score"] == 50 and m["band"] == "weak" and m["agreement"] == 100
    assert m["coverage"]["found"] == 3 and len(m["coverage"]["missing"]) == 3


def test_pan_inside_gstin_is_compared_to_the_pan_card():
    m = build([Source("pan_card", "p.png", {"pan": "AAACK1234C"}), Source("gst_certificate", "g.png", {"gstin": "27AAACX9999C1Z5"}),
               Source("typed", "", {"pan": "AAACK1234C"})])
    assert cell(m, "gst_certificate", "pan")["state"] == "bad"
