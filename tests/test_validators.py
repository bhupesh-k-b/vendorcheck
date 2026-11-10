import pytest
from vendorcheck import validators as v

VALID = ["27AAPFU0939F1ZV", "33AAACZ4322M1ZA", "29AAACI4798L1ZU", "33AADCD4946L1ZH", "29AAACR4849R1CS",
         "24AAACR4849R1ZR", "33AABCZ7092H1Z3"]


@pytest.mark.parametrize("g", VALID)
def test_check_digit_vectors(g):
    assert v.gstin_check_char(g[:14]) == g[14]


def test_invalid_check_digit():
    assert v.gstin_check_char("33AAACZ4322M1Z") == "A"
    r = v.check_gstin("33AAACZ4322M1ZB")
    assert not r.ok and r.code == "check_digit"


def test_regular_gstins_pass_r06():
    for g in ["27AAPFU0939F1ZV", "33AAACZ4322M1ZA", "29AAACI4798L1ZU", "33AADCD4946L1ZH", "24AAACR4849R1ZR", "33AABCZ7092H1Z3"]:
        assert v.check_gstin(g).ok, g


def test_tax_collector_gstin_passes_checksum_but_fails_r06():
    r = v.check_gstin("29AAACR4849R1CS")
    assert not r.ok and r.code == "tax_collector"
    assert v.gstin_check_char("29AAACR4849R1C") == "S"   # the check digit itself is fine


def test_sandbox_gstin_is_special_cased_not_a_real_checksum():
    # gstinapi's free sample GSTIN has state code 00 and a non-matching check digit: it is allowed through
    # only so the connectivity test can run, and its evidence is mode "sandbox" (never satisfies approval).
    assert v.gstin_check_char(v.SANDBOX_GSTIN[:14]) != v.SANDBOX_GSTIN[14]
    r = v.check_gstin(v.SANDBOX_GSTIN)
    assert r.ok and r.code == "sandbox"


def test_pan_inside_gstin():
    assert v.pan_from_gstin("33AABCZ7092H1Z3") == "AABCZ7092H"
    assert v.pan_from_gstin("33AAACZ4322M1ZA") == "AAACZ4322M"


def test_pan_format_and_constitution():
    assert v.check_pan("AAACZ4322M").ok
    assert not v.check_pan("AAAXZ4322M").ok
    assert v.check_pan_constitution("AAACZ4322M", "Zoho Corporation Private Limited").ok
    assert not v.check_pan_constitution("AAAPZ4322M", "Zoho Corporation Private Limited").ok
    assert v.check_pan_constitution("AAAPZ4322M", "Ravi Traders").ok   # cannot tell -> advisory only
    # Eternal: PAN 5th char D vs name initial E is legitimate and never checked as blocking
    assert v.check_pan_constitution("AADCD4946L", "Eternal Limited").ok


def test_ifsc_format():
    assert v.check_ifsc_format("HDFC0000001").ok and v.check_ifsc_format("YESB0000262").ok
    assert not v.check_ifsc_format("HDFC1000001").ok


def test_cin():
    assert v.check_cin("U40100TN2010PTC075961", "Zoho Corporation Private Limited").ok
    assert v.check_cin("L93030DL2010PLC198141", "Eternal Limited").ok
    assert not v.check_cin("U40100TN2010PLC075961", "Zoho Corporation Private Limited").ok
    assert not v.check_cin("L93030DL2010PTC198141", "Eternal Limited").ok
    assert not v.check_cin("X93030DL2010PLC198141").ok


def test_account():
    assert v.check_account("00011020001772", "00011020001772").ok
    assert not v.check_account("00011020001772", "00011020001773").ok
    assert not v.check_account("1234").ok


def test_name_normalise_and_match():
    assert v.normalise_name("M/S Zoho Corp. Pvt. Ltd.") == "ZOHO CORP PRIVATE LIMITED"
    assert v.normalise_name("Tata & Sons Ltd") == "TATA AND SONS LIMITED"
    assert v.names_match("ZOHO CORPORATION PRIVATE LIMITED", "Zoho Corporation Pvt Ltd")
    assert v.names_match("Zoho Corporation Private Limited", "Zoho Payment Technologies Private Limited") is False
    assert not v.names_match("Eternal Limited", "ZOMATO LIMITED")


def test_udyam_number_keeps_its_hyphens_and_validates():
    assert v.check_udyam("UDYAM-MH-26-0012345").ok and v.check_udyam(" udyam-gj-01-0045678 ").ok
    assert not v.check_udyam("UDYAM-MH-26-12345").ok and not v.check_udyam("UDYAMMH260012345").ok


def test_mask():
    assert v.mask("33AAACZ4322M1ZA") == "•••••••••••M1ZA"
    assert v.mask("1234") == "1234"
