"""The deterministic extractor, tested on the exact OCR text of the specimen documents (no model involved)."""
from vendorcheck import extract as x

PAN_CARD = "INCOME TAX DEPARTMENT\nGOVT. OF INDIA\nPermanent Account Number Card\nAAACK5521D\nName\nKAVERI PRECISION COMPONENTS PRIVATE LIMITED\nDate of Incorporation / Formation\n12 March 2014"
GST = ("Government of India\nForm GST REG-06\nREGISTRATION CERTIFICATE\nRegistration Number  27AAACK5521D1ZY\n1. Legal Name\nKAVERI PRECISION COMPONENTS PRIVATE LIMITED\n"
       "2. Trade Name, if any\nKAVERI PRECISION COMPONENTS\n3. Constitution of Business\nPrivate Limited Company\n5. Date of Liability 01/07/2017")
CHEQUE = "SPECIMEN CANCELLED CHEQUE\nPay\nRupees\nA/c No.  50200045678921\nIFSC  HDFC0000001\nFor  KAVERI PRECISION COMPONENTS PRIVATE LIMITED\nCANCELLED"
NEFT = ("FORM FOR AVAILING NEFT/RTGS MODE OF PAYMENT\n2 Name ( as in Bank A/c  MUNITIONS INDIA LIMITED O F KHAMARIA\n3 Bank A/c No.  40436892598\n"
        "5 Name of the Bank  State Bank of India\n8 IFSC Code of the Bank Branch  SBIN0003228")
INCORP = "Certificate of Incorporation\nI hereby certify that\nKAVERI PRECISION COMPONENTS PRIVATE LIMITED\nis this day incorporated\nThe Corporate Identity Number of the company is\nU29253MH2014PTC152873\nRegistrar of Companies, Maharashtra"
FILING = ("ETERNAL LIMITED (Formerly known as Zomato Limited)\nCIN: L93030DL2010PLC198141\nScrip Code: 543320\nPursuant to Regulation 30 of the SEBI Listing Regulations\n"
          "National Stock Exchange of India Limited")
FORM = ("Vendor Registration Request Form\n01 Name of the Company/ Vendor :  KAVERI PRECISION COMPONENTS PRIVATE LIMITED\nEmail:  ap@kaveri.example Mobile:  9822000123\n"
        "AccountNo.:  50200045678912\nIFSCCode:  HDFC0000001\nGSTIN 27AAACK5521D1ZY\nPAN AAACK5512D")


def fields(page):
    return {(f["doc_type"], f["field"]): f["value"] for f in page["fields"]}


def test_pan_card():
    p = x.read_page(PAN_CARD)
    assert p["types"] == ["pan_card"] and fields(p)[("pan_card", "pan")] == "AAACK5521D"
    assert fields(p)[("pan_card", "legal_name")] == "KAVERI PRECISION COMPONENTS PRIVATE LIMITED" and not p["missing"]


def test_gst_certificate_reads_gstin_and_names_and_does_not_double_count_the_pan_inside():
    p = x.read_page(GST)
    f = fields(p)
    assert p["types"] == ["gst_certificate"] and f[("gst_certificate", "gstin")] == "27AAACK5521D1ZY"
    assert f[("gst_certificate", "legal_name")] == "KAVERI PRECISION COMPONENTS PRIVATE LIMITED"
    assert ("gst_certificate", "pan") not in f            # the PAN inside a GSTIN is not a separate PAN token


def test_cheque_account_ifsc_and_holder():
    p = x.read_page(CHEQUE)
    f = fields(p)
    assert "cancelled_cheque_or_bank_letter" in p["types"]
    assert f[("cancelled_cheque_or_bank_letter", "bank_account")] == "50200045678921"
    assert f[("cancelled_cheque_or_bank_letter", "ifsc")] == "HDFC0000001"
    assert f[("cancelled_cheque_or_bank_letter", "account_holder")].startswith("KAVERI PRECISION")


def test_neft_form_is_a_bank_details_form_in_another_partys_name():
    p = x.read_page(NEFT)
    f = fields(p)
    assert p["types"] == ["bank_details_form"]
    assert f[("bank_details_form", "bank_account")] == "40436892598" and f[("bank_details_form", "ifsc")] == "SBIN0003228"
    assert f[("bank_details_form", "account_holder")].startswith("MUNITIONS INDIA")


def test_page_with_a_form_and_a_cheque_gets_both_document_types():
    p = x.read_page(NEFT + "\n" + CHEQUE)
    assert {"bank_details_form", "cancelled_cheque_or_bank_letter"} <= set(p["types"])


def test_incorporation_certificate_cin_and_name():
    f = fields(x.read_page(INCORP))
    assert f[("incorporation_or_name_change_certificate", "cin")] == "U29253MH2014PTC152873"
    assert f[("incorporation_or_name_change_certificate", "legal_name")] == "KAVERI PRECISION COMPONENTS PRIVATE LIMITED"


def test_exchange_filing_with_rename():
    p = x.read_page(FILING)
    f = fields(p)
    assert p["types"] == ["stock_exchange_filing"]
    assert f[("stock_exchange_filing", "previous_name")] == "Zomato Limited" and f[("stock_exchange_filing", "new_name")] == "ETERNAL LIMITED"


def test_registration_form_fields():
    f = fields(x.read_page(FORM))
    assert f[("vendor_registration_form", "legal_name")] == "KAVERI PRECISION COMPONENTS PRIVATE LIMITED"
    assert f[("vendor_registration_form", "bank_account")] == "50200045678912" and f[("vendor_registration_form", "ifsc")] == "HDFC0000001"
    assert f[("vendor_registration_form", "gstin")] == "27AAACK5521D1ZY" and f[("vendor_registration_form", "pan")] == "AAACK5512D"
    assert f[("vendor_registration_form", "contact_email")] == "ap@kaveri.example"


def test_unrecognised_text_is_left_undecided_for_the_ai_fallback():
    p = x.read_page("Some long paragraph about a topic that matches no known document type. " * 4)
    assert p["types"] == [] and p["undecided"] and p["fields"] == []
