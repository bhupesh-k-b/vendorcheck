"""'Use a real example' presets (section 7 of the brief). All identifiers are public business data.

Company bank accounts are not public, so the presets use Cashfree's PUBLISHED TEST account numbers,
labelled 'test account number' in the UI. Contacts are placeholders on the reserved example.com domain."""

COMMERCIAL = {"vendor_type": "services", "expense_category": "Software & IT services", "department_owner": "IT", "negotiated_terms": "Net 45", "system_terms": "45"}
CONTACT = {"contact_name": "Accounts desk", "contact_email": "accounts@example.com", "contact_phone": "9999999999", **COMMERCIAL}

ZOHO = {"legal_name": "Zoho Corporation Private Limited", "gstin": "33AAACZ4322M1ZA", "pan": "AAACZ4322M", "cin": "U40100TN2010PTC075961",
        "bank_account": "00011020001772", "bank_account_confirm": "00011020001772", "ifsc": "HDFC0000001", **CONTACT}

EXAMPLES = {
    "zoho": {"label": "Zoho", "note": "Happy path. GST is fetched live; ends Pending until finance confirms the bank account.", "fields": ZOHO},
    "infosys": {"label": "Infosys", "note": "About 40 GSTINs under one PAN: record the GSTIN of the supplying state (Karnataka).",
                "fields": {"legal_name": "Infosys Limited", "gstin": "29AAACI4798L1ZU", "pan": "AAACI4798L", "cin": "L85110KA1981PLC013115",
                           "bank_account": "000890289871772", "bank_account_confirm": "000890289871772", "ifsc": "SCBL0036078", **CONTACT}},
    "eternal": {"label": "Eternal (declares Eternal Limited)", "samples": ["eternal_nse_name_change_filing.pdf"],
                "note": "E1: renamed company, with the public NSE filing attached. Use this if the live GST record still reads ZOMATO LIMITED.",
                "fields": {"legal_name": "Eternal Limited", "gstin": "33AADCD4946L1ZH", "pan": "AADCD4946L", "cin": "L93030DL2010PLC198141",
                           "bank_account": "02014457596969", "bank_account_confirm": "02014457596969", "ifsc": "CITI0000001", **CONTACT}},
    "eternal_old": {"label": "Eternal (declares old name Zomato Limited)", "samples": ["eternal_nse_name_change_filing.pdf"],
                    "note": "E1 the other way round: use this if the live GST record already reads ETERNAL LIMITED (an old letterhead).",
                    "fields": {"legal_name": "Zomato Limited", "gstin": "33AADCD4946L1ZH", "pan": "AADCD4946L", "cin": "L93030DL2010PLC198141",
                               "bank_account": "02014457596969", "bank_account_confirm": "02014457596969", "ifsc": "CITI0000001", **CONTACT}},
    "tcs": {"label": "TCS wrong GSTIN", "note": "E2: a tax-collector GSTIN (14th character C). Flagged instantly, no API credit spent.",
            "fields": {"legal_name": "Tata Consultancy Services Limited", "gstin": "29AAACR4849R1CS", "pan": "AAACR4849R",
                       "bank_account": "000100289877623", "bank_account_confirm": "000100289877623", "ifsc": "SBIN0008752", **CONTACT}},
    "zoho_duplicate": {"label": "Zoho duplicate", "note": "Duplicate check: the same PAN, GSTIN and bank account as an approved Zoho. Needs the Zoho case approved first.",
                       "fields": ZOHO},
    "zoho_lookalike": {"label": "Zoho look-alike", "note": "E3: Zoho's details but the GSTIN of its sister company. The PAN inside the GSTIN differs.",
                       "fields": {**ZOHO, "gstin": "33AABCZ7092H1Z3"}},
    "zoho_bank_change": {"label": "Zoho new bank account", "note": "E4: new bank details on an already-approved vendor (needs demo step 1 first).",
                         "fields": {**ZOHO, "bank_account": "026291800001191", "bank_account_confirm": "026291800001191", "ifsc": "YESB0000262"}},
}
KAVERI = {"country": "IN", "legal_name": "Kaveri Precision Components Private Limited", "gstin": "27AAACK5521D1ZY", "pan": "AAACK5521D",
          "cin": "U29253MH2014PTC152873", "bank_account": "50200045678912", "bank_account_confirm": "50200045678912", "ifsc": "HDFC0000001",
          "contact_name": "Ravi Kulkarni", "contact_email": "ap@kaveri.example", "contact_phone": "9822000123", **COMMERCIAL}
MEHTA = {"country": "IN", "legal_name": "Mehta and Sons Traders", "gstin": "24AAAPM4521K1ZY", "pan": "AAAPM4521K", "udyam_number": "UDYAM-GJ-01-0045678",
         "bank_account": "30110045671234", "bank_account_confirm": "30110045671234", "ifsc": "HDFC0000001",
         "contact_name": "Rajesh Mehta", "contact_email": "accounts@mehta-traders.example", "contact_phone": "9898000123", **COMMERCIAL}
EXAMPLES["kaveri_clean"] = {
    "label": "Document pack: consistent", "samples": ["kaveri_pack_clean.pdf"],
    "note": "SPECIMEN, fictional company. One long PDF: the filled 11-page registration form + PAN card + GST certificate + cancelled cheque + incorporation certificate, all consistent. (A fictional GSTIN is correctly 'not found' by the live GST source.)",
    "fields": KAVERI}
EXAMPLES["kaveri_messy"] = {
    "label": "Document pack: inconsistent", "samples": ["kaveri_pack_messy.pdf"],
    "note": "SPECIMEN, fictional company. Same pack with planted problems: the PAN on the form has two digits swapped, the cheque shows a different account number and no IFSC, the form has no CIN. Watch the consistency table flag each one.",
    "fields": {"legal_name": "Kaveri Precision Components Private Limited", "gstin": "27AAACK5521D1ZY", "pan": "AAACK5521D",
              "bank_account": "50200045678912", "bank_account_confirm": "50200045678912", "ifsc": "HDFC0000001",
              "contact_name": "Ravi Kulkarni", "contact_email": "ap@kaveri.example", "contact_phone": "9822000123"}}
_INTL_CONTACT = {"contact_name": "Accounts desk", "contact_email": "accounts@example.com", "contact_phone": "+1 555 0100", **COMMERCIAL}
EXAMPLES["us_vendor"] = {
    "label": "US vendor (EIN)", "note": "Fictional US company. Format and checksum are checked; there is no register we can query, so a person confirms the EIN on the official site. No Indian source is called.",
    "fields": {"country": "US", "legal_name": "Lakeview Industrial Supply LLC", "tax_id": "12-3456789", "bank_account": "123456789012", "routing_code": "021000021", **_INTL_CONTACT}}
EXAMPLES["eu_vendor"] = {
    "label": "German vendor (VAT + IBAN)", "note": "Fictional German company. VAT number shape, IBAN check digits and SWIFT country are checked; the VAT number is then confirmed by a person on EU VIES.",
    "fields": {"country": "DE", "legal_name": "Rheinland Werkzeug GmbH", "tax_id": "DE123456789", "iban": "DE89370400440532013000", "swift": "COBADEFFXXX", **_INTL_CONTACT}}
EXAMPLES["wrong_country"] = {
    "label": "Says US, gives an Indian GSTIN", "note": "The tax ID given is an Indian GSTIN but the vendor claims to be in the United States. Flagged instantly, and no Indian source is called.",
    "fields": {"country": "US", "legal_name": "Lakeview Industrial Supply LLC", "tax_id": "27AAACK5521D1ZY", "bank_account": "123456789012", "routing_code": "021000021", **_INTL_CONTACT}}
EXAMPLES["eu_wrong_iban"] = {
    "label": "German vendor, French IBAN", "note": "The IBAN belongs to France but the vendor says it is based in Germany.",
    "fields": {"country": "DE", "legal_name": "Rheinland Werkzeug GmbH", "tax_id": "DE123456789", "iban": "FR1420041010050500013M02606", "swift": "COBADEFFXXX", **_INTL_CONTACT}}
_C = {"contact_name": "Accounts desk", "contact_email": "accounts@example.com", "contact_phone": "+91 99999 99999", **COMMERCIAL}
EXAMPLES["rmc1_infosys"] = {
    "label": "RMC1 form: Infosys (original details)", "samples": ["rmc1_infosys_form_filled.pdf"],
    "note": "Your 11-page RMC1 vendor form filled with Infosys's public details, and nothing else attached. The vendor left the phone and TAN blank and sent no PAN card, GST certificate, cheque or address proof: the required-documents checklist lists what is missing.",
    "fields": {"country": "IN", "legal_name": "Infosys Limited", "gstin": "29AAACI4798L1ZU", "pan": "AAACI4798L", "cin": "L85110KA1981PLC013115",
               "bank_account": "000890289871772", "bank_account_confirm": "000890289871772", "ifsc": "SCBL0036078", **COMMERCIAL,
               "contact_name": "Accounts desk", "contact_email": "accounts@example.com", "contact_phone": "9999999999"}}
EXAMPLES["kaveri_complete"] = {
    "label": "One PDF with everything (Kaveri, MSME)", "samples": ["kaveri_complete_pack.pdf"],
    "note": "SPECIMEN, fictional. A single 17-page PDF: the RMC1 form plus PAN card, GST certificate, cancelled cheque, certificate of incorporation, electricity bill and Udyam certificate. Each page is identified, so the checklist finds all six documents.",
    "fields": {**KAVERI, "udyam_number": "UDYAM-MH-26-0012345"}}
EXAMPLES["mehta_separate"] = {
    "label": "Separate files (Mehta, proprietor)", "samples": ["mehta_pan_card.pdf", "mehta_gst_certificate.pdf", "mehta_cancelled_cheque.pdf", "mehta_udyam_certificate.pdf", "mehta_electricity_bill.pdf"],
    "note": "SPECIMEN, fictional proprietorship sending five separate files. Its electricity bill is for a different address than the GST registration, so the address is flagged. No certificate of incorporation is needed for a proprietor.",
    "fields": MEHTA}
EXAMPLES["orchid_wrong"] = {
    "label": "Wrong documents attached (Orchid)", "samples": ["orchid_wrong_documents.pdf"],
    "note": "SPECIMEN, fictional. The vendor attached a brochure, an unrelated invoice, someone else's PAN card and a bill: no GST certificate, cheque or incorporation certificate. The PAN card's name and number do not match the vendor.",
    "fields": {"country": "IN", "legal_name": "Orchid Garments Private Limited", "gstin": "33AAACO7788P1ZN", "pan": "AAACO7788P", "bank_account": "30110045671234", "bank_account_confirm": "30110045671234",
               "ifsc": "HDFC0000001", **_C}}
EXAMPLES["lakeview_pack"] = {
    "label": "US vendor with documents (Lakeview)", "samples": ["lakeview_us_pack.pdf"],
    "note": "SPECIMEN, fictional US company with a W-9, a bank confirmation letter and articles of organization. All signals say US.",
    "fields": {"country": "US", "legal_name": "Lakeview Industrial Supply LLC", "tax_id": "12-3456789", "bank_account": "123456789012", "routing_code": "021000021", "swift": "SPBKUS33",
               "contact_name": "Dana Cole", "contact_email": "dana@example.com", "contact_phone": "+1 312 555 0100", **COMMERCIAL}}
EXAMPLES["lakeview_indian_id"] = {
    "label": "Says US, documents US, but gives an Indian ID", "samples": ["lakeview_us_pack.pdf"],
    "note": "The US documents are consistent, but the tax ID typed is an Indian GSTIN. Flagged: it looks like an Indian ID, not a US one.",
    "fields": {"country": "US", "legal_name": "Lakeview Industrial Supply LLC", "tax_id": "27AAACK5521D1ZY", "bank_account": "123456789012", "routing_code": "021000021", "swift": "SPBKUS33",
               "contact_name": "Dana Cole", "contact_email": "dana@example.com", "contact_phone": "+1 312 555 0100", **COMMERCIAL}}
EXAMPLES["rheinland_pack"] = {
    "label": "German vendor with documents (Rheinland)", "samples": ["rheinland_eu_pack.pdf"],
    "note": "SPECIMEN, fictional German GmbH: VAT certificate, IBAN bank letter, commercial-register extract. No GSTIN anywhere: a German vendor has none.",
    "fields": {"country": "DE", "legal_name": "Rheinland Werkzeug GmbH", "tax_id": "DE123456789", "iban": "DE89370400440532013000", "swift": "COBADEFFXXX",
               "contact_name": "Anna Weber", "contact_email": "anna@example.com", "contact_phone": "+49 30 1234567", **COMMERCIAL}}
MUNITIONS = {"country": "IN", "legal_name": "Munitions India Limited", "gstin": "23AAOCM8781H2ZX", "pan": "AAOCM8781H",
             "bank_account": "40436892598", "bank_account_confirm": "40436892598", "ifsc": "SBIN0003228", "account_holder": "Munitions India Limited O F Khamaria",
             "contact_name": "Accounts desk", "contact_email": "accounts@example.com", "contact_phone": "9999999999", **COMMERCIAL}
EXAMPLES["munitions"] = {
    "label": "Munitions India Limited", "fields": MUNITIONS,
    "note": "Happy path on a real company. The GSTIN is checked live (Active, Regular). The bank account is in the name of Munitions India Limited O F Khamaria, "
            "the company's own unit, so the account name matches the vendor. Pending until finance confirms the bank, then Approved."}
EXAMPLES["munitions_form"] = {
    "label": "Munitions: RMC1 form, bank name matches", "samples": ["rmc1_munitions_form_filled.pdf"], "fields": MUNITIONS,
    "note": "The vendor form filled with Munitions India Limited's public details. Its bank pages are in Munitions' own name, so the account holder on the bank form, "
            "the typed holder and the legal name all agree. The other required documents are not attached, so the case waits on the vendor for them."}
EXAMPLES["happy_documents"] = {
    "label": "Kaveri: happy test case (all documents)", "samples": ["kaveri_happy_pack.pdf"], "simulate": True, "fields": KAVERI,
    "note": "SIMULATED test case on a fictional company. Typed details plus every required document (registration form, PAN card, GST certificate, cancelled cheque, "
            "certificate of incorporation, address proof), all consistent. The documents are read for real; only the GST registry answer is synthetic, because a fictional "
            "company cannot exist in the real registry. Pending until finance confirms the bank, then Approved. Never written to the vendor master."}
EXAMPLES["kaveri_holder_mismatch"] = {
    "label": "Bank account name differs (Kaveri)", "samples": ["kaveri_pack_clean.pdf"],
    "fields": {**KAVERI, "account_holder": "Ravi Kulkarni"},
    "note": "SPECIMEN, fictional. Everything agrees except the bank account holder: the vendor typed a person's name, while the company and the bank documents say Kaveri Precision Components. Flagged for finance."}
for _e in EXAMPLES.values():      # every sample that has bank details also says whose name the account is in
    _f = _e["fields"]
    if (_f.get("bank_account") or _f.get("iban")) and _f.get("legal_name") and "account_holder" not in _f:
        _e["fields"] = {**_f, "account_holder": _f["legal_name"]}
SAMPLE_FILES = {"kaveri_happy_pack.pdf", "rmc1_munitions_form_filled.pdf", "rmc1_infosys_form_filled.pdf", "kaveri_complete_pack.pdf", "mehta_pan_card.pdf", "mehta_gst_certificate.pdf", "mehta_cancelled_cheque.pdf",
                "mehta_udyam_certificate.pdf", "mehta_electricity_bill.pdf", "orchid_wrong_documents.pdf", "lakeview_us_pack.pdf", "rheinland_eu_pack.pdf","eternal_nse_name_change_filing.pdf", "blank_vendor_form.pdf", "infosys_vendor_form_typed.pdf",
                "kaveri_pack_clean.pdf", "kaveri_pack_messy.pdf", "kaveri_pan_card.png", "registration_form_blank.pdf"}
