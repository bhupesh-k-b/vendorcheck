from vendorcheck import countries as c


def test_indian_ids_are_recognised_as_india():
    assert c.detect("33AAACZ4322M1ZA")[0].country == "IN" and c.detect("33AAACZ4322M1ZA")[0].id_type == "GSTIN"
    assert c.detect("AAACZ4322M")[0].id_type == "PAN"
    assert c.detect("U40100TN2010PTC075961")[0].id_type == "CIN"


def test_the_users_case_an_indian_gstin_given_by_a_vendor_who_says_it_is_in_the_us():
    r = c.check_tax_id("US", "33AAACZ4322M1ZA")
    assert not r.ok and r.code == "wrong_country"
    assert "an Indian GSTIN" in r.message and "United States" in r.message


def test_us_ein_valid_and_invalid_prefix():
    assert c.check_tax_id("US", "12-3456789").ok
    assert c.check_tax_id("US", "123456789").ok                 # digits only is accepted for the claimed country
    assert not c.check_tax_id("US", "00-1234567").ok            # 00 is not an IRS prefix


def test_ssn_is_refused_as_a_personal_id():
    r = c.check_tax_id("US", "123-45-6789")
    assert not r.ok and r.code == "personal"


def test_eu_vat_numbers_by_country_prefix():
    assert c.check_tax_id("DE", "DE123456789").ok
    assert c.check_tax_id("GR", "EL123456789").ok                # Greece uses the EL prefix
    r = c.check_tax_id("DE", "FR12345678901")
    assert not r.ok and r.code == "wrong_country" and "a French VAT number" in r.message
    assert c.check_tax_id("FR", "FR12345678901").ok


def test_uk_vat_checksum():
    assert c.check_tax_id("GB", "GB999999973").ok                 # HMRC's published valid test number
    bad = c.check_tax_id("GB", "GB999999974")
    assert not bad.ok and bad.code == "invalid"


def test_abn_checksum():
    assert c.check_tax_id("AU", "51 824 753 556").ok
    assert not c.check_tax_id("AU", "51 824 753 557").ok


def test_unrecognised_for_the_claimed_country_names_the_expected_format():
    r = c.check_tax_id("DE", "HELLO123")
    assert not r.ok and r.code == "unrecognised" and "VAT" in r.message


def test_infer_country_from_identifiers():
    assert c.infer_country({"gstin": "33AAACZ4322M1ZA"}) == "IN"
    assert c.infer_country({"tax_id": "DE123456789"}) == "DE"
    assert c.infer_country({"tax_id": "123456789"}) == ""        # ambiguous: many countries share nine digits
    assert c.infer_country({"iban": "DE89 3704 0044 0532 0130 00"}) == "DE"


def test_iban_checksum_vectors():
    for good in ["DE89370400440532013000", "GB82WEST12345698765432", "FR1420041010050500013M02606", "NL91ABNA0417164300"]:
        assert c.iban_ok(good), good
    assert not c.iban_ok("DE89370400440532013001")


def test_aba_routing_checksum():
    assert c.aba_ok("021000021") and c.aba_ok("011401533") and not c.aba_ok("021000022")


def test_foreign_bank_checks():
    assert c.check_foreign_bank("DE", iban="DE89 3704 0044 0532 0130 00") == []
    assert [i.code for i in c.check_foreign_bank("DE", iban="FR1420041010050500013M02606")] == ["wrong_country"]
    assert [i.code for i in c.check_foreign_bank("DE", iban="DE89370400440532013001")] == ["invalid"]
    assert c.check_foreign_bank("US", bank_account="123456789012", routing_code="021000021") == []
    assert c.check_foreign_bank("US", bank_account="123456789012", routing_code="021000022")[0].code == "invalid"
    assert c.check_foreign_bank("US", bank_account="123456789012")[0].code == "missing"
    assert c.check_foreign_bank("DE", iban="DE89370400440532013000", swift="COBADEFFXXX") == []
    assert c.check_foreign_bank("DE", iban="DE89370400440532013000", swift="CHASUS33")[0].code == "wrong_country"
