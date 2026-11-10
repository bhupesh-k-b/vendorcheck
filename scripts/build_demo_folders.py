"""Builds demo_documents/: the documents a vendor uploads at registration, organised by scenario (happy path and edge cases).

    .venv/bin/python scripts/build_demo_folders.py

Sources are the generated packs in samples/ (run scripts/make_packs.py first if they are missing). The packs are fictional,
watermarked SPECIMEN documents; only the registration form carries a real company's public details, on the vendor's own form."""
import shutil
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
OUT = ROOT / "demo_documents"

# page ranges (1-based, inclusive) inside kaveri_complete_pack.pdf
KAVERI = {"registration_form": (1, 11), "pan_card": (12, 12), "gst_certificate": (13, 13), "cancelled_cheque": (14, 14),
          "certificate_of_incorporation": (15, 15), "address_proof_electricity_bill": (16, 16), "udyam_certificate": (17, 17)}


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n")


def copy(name: str, dest: Path, new_name: str | None = None):
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(SAMPLES / name, dest / (new_name or name))


def pick(src: pymupdf.Document, ranges: list[tuple[int, int]], path: Path):
    out = pymupdf.open()
    for a, b in ranges:
        out.insert_pdf(src, from_page=a - 1, to_page=b - 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    src = pymupdf.open(SAMPLES / "kaveri_complete_pack.pdf")
    happy = OUT / "01_happy_path"
    edge = OUT / "02_edge_cases"

    # ---------- happy path ----------
    sep = happy / "A_separate_files"
    for i, (name, (a, b)) in enumerate(KAVERI.items(), 1):
        pick(src, [(a, b)], sep / f"{i:02d}_{name}.pdf")
    copy("kaveri_complete_pack.pdf", happy / "B_one_combined_pdf")
    copy("kaveri_happy_pack.pdf", happy / "C_happy_test_case")

    # ---------- edge cases ----------
    pick(src, [(1, 11), (13, 13), (15, 15), (17, 17)], edge / "01_missing_documents" / "kaveri_pack_without_pan_cheque_address.pdf")
    copy("orchid_wrong_documents.pdf", edge / "02_wrong_documents_attached")
    copy("rmc1_infosys_form_filled.pdf", edge / "03_other_companys_bank_documents")
    for f in ("mehta_pan_card.pdf", "mehta_gst_certificate.pdf", "mehta_cancelled_cheque.pdf", "mehta_udyam_certificate.pdf", "mehta_electricity_bill.pdf"):
        copy(f, edge / "04_address_proof_mismatch")
    copy("kaveri_pack_messy.pdf", edge / "05_inconsistent_details_across_documents")
    copy("kaveri_pan_card.png", edge / "06_phone_photo_of_a_document")
    copy("eternal_nse_name_change_filing.pdf", edge / "07_company_renamed")
    copy("lakeview_us_pack.pdf", edge / "08_us_vendor_with_documents")
    copy("rheinland_eu_pack.pdf", edge / "09_german_vendor_with_documents")
    (edge / "10_typed_only_no_documents").mkdir(parents=True, exist_ok=True)
    (edge / "14_custom_identity_details").mkdir(parents=True, exist_ok=True)
    for f in ("mehta_pan_card.pdf", "mehta_gst_certificate.pdf", "mehta_cancelled_cheque.pdf", "mehta_udyam_certificate.pdf", "mehta_electricity_bill.pdf", "mehta_fssai_specimen.pdf"):
        copy(f, edge / "15_fssai_licence_item")
    for f in ("mehta_pan_card.pdf", "mehta_gst_certificate.pdf", "mehta_cancelled_cheque.pdf", "mehta_udyam_certificate.pdf", "mehta_electricity_bill.pdf", "mehta_aadhaar_specimen.pdf"):
        copy(f, edge / "13_custom_compliance_document")
    copy("rmc1_munitions_form_filled.pdf", edge / "11_bank_account_name_matches")
    copy("kaveri_pack_clean.pdf", edge / "12_bank_account_name_differs")

    # ---------- READMEs ----------
    write(OUT / "00_READ_ME_FIRST.md", TOP)
    write(happy / "README.md", HAPPY)
    for folder, text in EDGE.items():
        write(edge / folder / "README.md", text)
    write(edge / "README.md", EDGE_INDEX)
    n = sum(1 for p in OUT.rglob("*") if p.is_file() and p.suffix != ".md")
    print(f"demo_documents/ built: {n} document files, {sum(1 for _ in OUT.rglob('README.md'))} READMEs")


TOP = """
# Documents a vendor uploads at registration

| # | Document | Required when | What VendorCheck checks | Where to verify |
|---|----------|---------------|-------------------------|-----------------|
| 1 | Vendor registration form | Always | Every typed detail is cross-checked against the other documents | n/a |
| 2 | PAN card | Every Indian vendor | PAN format, holder type, same PAN inside the GSTIN | Income Tax e-filing: Verify Your PAN |
| 3 | GST registration certificate | A GSTIN was given | GSTIN format and check digit, live registry status, legal name | GST portal: Search Taxpayer |
| 4 | Cancelled cheque or bank confirmation letter | Always (bank details need a document) | Account number, IFSC, account holder is the vendor itself | RBI IFSC directory |
| 5 | Address proof | To match the registered GST address | PIN code and address match the GST registration | n/a |
| 6 | Udyam registration certificate | The vendor claims MSME status | Udyam number format, name; a person checks the official page | Udyam portal |
| 7 | Certificate of incorporation | Companies and LLPs | CIN format and class, company name, status | MCA master data |

Non-Indian vendors upload the local equivalents instead (tax registration such as W-9 or VAT certificate, a bank letter with IBAN or
routing details, a business registration extract). India-only checks are skipped for them.

A vendor can send **one combined PDF** or **separate files**. Pages are identified one by one, so both work.

## Folders

- `01_happy_path/` a complete, consistent document set (separate files and one combined PDF)
- `02_edge_cases/` what can go differently, one folder per situation, each with a README saying what to expect

Every document in these folders is a fictional **SPECIMEN** with a watermark. The one exception is the registration form in
`02_edge_cases/03_other_companys_bank_documents`, which is the vendor form filled with a real company's public details. No imitation
government documents are made for real companies.

## How to use a folder

1. Open VendorCheck, choose **New submission**.
2. Either use **Load a sample** (the README of each folder names the entry), or drag the files from the folder into the upload box and type the details.
3. Submit and watch the run.
"""

HAPPY = """
# 01 Happy path: a complete, consistent document set

**Vendor:** Kaveri Precision Components Private Limited (fictional, MSME, company). All six required documents, details agree everywhere.

| Folder | What it is | Sample entry |
|--------|------------|--------------|
| `A_separate_files/` | The seven documents as separate files | upload all seven files |
| `B_one_combined_pdf/` | The same documents in one 17-page PDF | **Load a sample → One PDF with everything (Kaveri, MSME)** |

Files in `A_separate_files/`: registration form (11 pages), PAN card, GST registration certificate, cancelled cheque,
certificate of incorporation, address proof (electricity bill), Udyam certificate.

## What you should see

- The required-documents table shows all six documents **Found**, with the page each was found on (combined PDF) or the file name (separate files).
- Consistency across documents scores **100 / Strong**: legal name, PAN, GSTIN, CIN, bank account and IFSC agree across every document.
- The document viewer beside the results shows each page with what was read from it.
- Offline checks pass: GSTIN check digit, PAN structure, IFSC found in the RBI list.

## Why this company ends "Pending" and not "Approved"

Approval needs the GST registry to confirm the GSTIN. Kaveri is fictional, so the registry correctly answers **not found**, and the
case waits on the vendor. VendorCheck never fakes a registry answer, and sample or recorded data can never approve a real vendor.

To see the **complete flow with every document attached ending in Approved**, use `C_happy_test_case/` : **Load a sample → Kaveri: happy test case (all documents)**.
Typed details plus the registration form, PAN card, GST certificate, cancelled cheque, certificate of incorporation and address proof. All five required documents are found,
consistency is 100 (Strong), it waits on Finance for the bank, and two people approve. The documents are read for real (14 pages). It is labelled **Simulated** because the
fictional company's registry answer is synthetic, and the vendor ID it receives is flagged Simulated.

For a **live approved** case use the real-company example (typed details, checked live): **Load a sample → Zoho**, then finance confirms
the bank account and a second person approves. To see an approval with documents, upload a real company's own documents (with its
permission) into this folder structure: the checklist and consistency view work the same way.
"""

EDGE_INDEX = """
# 02 Edge cases: what can go differently

| Folder | Situation | Expected outcome |
|--------|-----------|------------------|
| `01_missing_documents` | Vendor skips PAN card, cancelled cheque and address proof | Pending on the vendor, email lists exactly what is missing |
| `02_wrong_documents_attached` | Brochure, unrelated invoice, someone else's PAN card | Pending on the vendor, each file explained |
| `03_other_companys_bank_documents` | Bank documents belong to a different company | Those pages are excluded, vendor asked for their own |
| `04_address_proof_mismatch` | Electricity bill shows a different address from the GST registration | Address mismatch flagged |
| `05_inconsistent_details_across_documents` | PAN digits swapped on the form, other planted differences | Conflicts shown in the consistency table, vendor asked to confirm |
| `06_phone_photo_of_a_document` | A photographed PAN card instead of a clean scan | Read with lower confidence; key numbers read twice and confirmed |
| `07_company_renamed` | Company changed its legal name | Approved with an explanation when the filing shows the rename |
| `08_us_vendor_with_documents` | US company, W-9 and bank letter | No India checks; person confirms the register; Indian ID typed instead is flagged |
| `09_german_vendor_with_documents` | German company, VAT certificate, IBAN | VAT shape and IBAN checked; France IBAN for a German company is flagged |
| `10_typed_only_no_documents` | Problems that need no files | See its README (wrong GSTIN type, look-alike, duplicate vendor, bank change, wrong country ID) |
| `11_bank_account_name_matches` | The name on the bank account is the vendor's own (Munitions India Limited) | Holder agrees across the typed form, the bank form and the legal name; the unit account counts as the company's |
| `13_custom_compliance_document` | A document your company needs (Aadhaar) is added in Settings; one it does not (Udyam) is switched off | Shown as Found or Missing in the full case, requested in the vendor email |
| `15_fssai_licence_item` | An item with both a number and a document (FSSAI licence) is added | Number and document shown as found or missing in the checklist, summary card, consistency table and dashboard |
| `14_custom_identity_details` | An identity detail is added (TAN) and one is switched off (CIN) | New field on the form, format-checked live and on submit; the switched-off one disappears everywhere |
| `12_bank_account_name_differs` | The typed account holder is a person, the bank document says the company | Holder flagged in the consistency table; finance reviews |
"""

EDGE = {
"01_missing_documents": """
# Missing documents

**File:** `kaveri_pack_without_pan_cheque_address.pdf`: the registration form, GST certificate, certificate of incorporation and Udyam certificate only.

**How to run:** New submission → upload the file. Type the Kaveri details, or use **Load a sample → One PDF with everything (Kaveri, MSME)**
and replace its file with this one.

**Expected:** the required-documents table marks PAN card and address proof **Missing** (red). The cancelled-cheque row shows **Wrong party**: the only
bank pages in this pack are the form's own bank pages, which name a different company, so they are not accepted as the vendor's bank document. The case is
Pending on the vendor, and the email draft lists what to send in plain language.

**What else can go differently:** only one document sent; documents sent in a different language; a scan where pages are upside down or unreadable
(the file is marked not legible and the vendor is asked to resend).
""",
"02_wrong_documents_attached": """
# Wrong documents attached

**File:** `orchid_wrong_documents.pdf`: a brochure, an unrelated invoice, someone else's PAN card and a bill.

**How to run:** **Load a sample → Wrong documents attached (Orchid)**.

**Expected:** pages are identified one by one. The brochure and invoice are recognised as not onboarding documents; the PAN card belongs to
another person, so it is not used. Required documents show as missing and the vendor is asked to send the right ones.

**What else can go differently:** a correct document for the wrong year or wrong entity; the same file uploaded twice (stored once by its hash).
""",
"03_other_companys_bank_documents": """
# Another company's bank documents inside the pack

**File:** `rmc1_infosys_form_filled.pdf`: the 11-page vendor form filled with Infosys's public details. Its bank pages (9 and 10) name a different
company as account holder.

**How to run:** **Load a sample → RMC1 form: Infosys (original details)**.

**Expected:** the bank pages are recognised as another party's, shown with a warning in the document viewer, and **not used** as the vendor's bank
details. Because no bank document in the vendor's own name exists, the vendor is asked to send one. The other company is never named in the email.

**What else can go differently:** a cheque in the name of a director rather than the company; a joint account; a bank letter older than expected.
""",
"04_address_proof_mismatch": """
# Address proof does not match the GST registration

**Files:** `mehta_*.pdf`: PAN card, GST certificate, cancelled cheque, Udyam certificate and an electricity bill (fictional proprietorship, five separate files).

**How to run:** **Load a sample → Separate files (Mehta, proprietor)**.

**Expected:** the address on the electricity bill (PIN code and address text) is compared with the GST registration address and **does not match**.
The consistency table marks the address cell, and the vendor is asked for an address proof matching the registered address.

**What else can go differently:** a rent agreement for a different branch; a PO-box address; an address in a different state (GSTIN state code differs).
""",
"05_inconsistent_details_across_documents": """
# Inconsistent details across documents

**File:** `kaveri_pack_messy.pdf`: the same pack as the happy path with planted problems: the PAN on the form has two digits swapped, and other values differ between documents.

**How to run:** **Load a sample → Document pack: inconsistent**.

**Expected:** the consistency table shows ✗ where documents disagree, with a "Why these are flagged" list. The score drops and the vendor is asked to confirm the values.

**What else can go differently:** legal name spelled differently on the cheque; account holder differs from the vendor; IFSC does not exist.
""",
"06_phone_photo_of_a_document": """
# A photo instead of a scan

**File:** `kaveri_pan_card.png`: a PAN card as a phone-style image.

**How to run:** New submission → upload the image with the Kaveri typed details.

**Expected:** local text recognition reads the image. Key numbers (PAN, GSTIN, account) on photos and scans are read twice and must agree; a low-confidence
read asks the vendor to confirm the value instead of guessing.

**What else can go differently:** blurred or cropped photos; handwriting; a photo taken at an angle; HEIC files from iPhones (accepted).
""",
"07_company_renamed": """
# Company renamed

**File:** `eternal_nse_name_change_filing.pdf`: a public stock-exchange filing recording a name change.

**How to run:** **Load a sample → Eternal (declares Eternal Limited)**, or the "old name" variant if the live registry already shows the new name.

**Expected:** the declared name differs from the registry name, but the filing proves the rename. The case is **approved with an explanation** (once finance confirms the bank account).

**What else can go differently:** a name difference with no evidence of a rename goes to procurement for a decision.
""",
"08_us_vendor_with_documents": """
# US vendor with documents

**File:** `lakeview_us_pack.pdf`: W-9, bank confirmation letter and articles of organization (fictional US company).

**How to run:** **Load a sample → US vendor with documents (Lakeview)**. For the problem variant: **Says US, documents US, but gives an Indian ID**.

**Expected:** no India-only checks (no GSTIN or PAN verification). The EIN and routing number are checked for shape and checksum only; a person confirms the
official register and finance confirms the bank. In the variant, an Indian GSTIN typed for a US vendor is flagged as an ID that belongs to another country.

**What else can go differently:** documents from several countries in one pack; a phone code or address that points to another country.
""",
"09_german_vendor_with_documents": """
# German vendor with documents

**File:** `rheinland_eu_pack.pdf`: VAT certificate, IBAN bank letter and commercial-register extract (fictional German GmbH).

**How to run:** **Load a sample → German vendor with documents (Rheinland)**. For the problem variant: **German vendor, French IBAN**.

**Expected:** VAT number shape, IBAN check digits and the SWIFT country are checked. No GSTIN is expected anywhere. In the variant, the IBAN belongs to France while
the vendor says Germany, so it is flagged.

**What else can go differently:** a VAT number for a different EU country; an IBAN that fails its check digits.
""",
"11_bank_account_name_matches": """
# Bank account name matches the vendor

**File:** `rmc1_munitions_form_filled.pdf`: the vendor form filled with Munitions India Limited's public details. Its bank pages (9 and 10) are in Munitions' own name.

**How to run:** **Load a sample → Munitions: RMC1 form, bank name matches**. For the typed-only happy path on the same company: **Load a sample → Munitions India Limited**
(checked live, finance confirms the bank, a second person approves).

**Expected:** the consistency table shows ✓ under **Account no., IFSC and Holder** on the typed form, the registration form and the bank form. "Munitions India Limited O F Khamaria"
is a unit account of the company, so it matches the legal name. The case still waits on the vendor for the documents not attached (PAN card, GST certificate, address proof, incorporation certificate).

**What else can go differently:** an account in a director's name; a different company's name (the pages are shown as another party's and not used); a joint account.
""",
"15_fssai_licence_item": """
# An item with a number and a document (FSSAI licence)

**Files:** the five Mehta documents plus `mehta_fssai_specimen.pdf` (a specimen licence page, fictional number).

**How to run:**
1. **Settings → Extra compliance items →** template **FSSAI licence → Add item → Save policy.** One item carries both the **number** (14 digits) and the **document** (recognised by "FSSAI"). Optionally switch **Certificate of incorporation** off under *Compliance documents*.
2. **Load a sample → Separate files (Mehta, proprietor)** → Submit. The case shows **FSSAI licence: Missing** in *Required documents*, a **Compliance items** card ("Document missing · Number not provided"), a **Not provided** row and an FSSAI column in the *Consistency table*, and **Missing: FSSAI licence** on the dashboard row.
3. **Load a sample → Mehta with FSSAI licence** → Submit. The document is **Found**, the number is read from the page and compared with the typed one (the consistency table shows ✓ and the evidence summary says *Match*).

Everything a document states is read and compared, not just its number: the **name**, **premises address**, **kind of business**, **reference number**, **date** and validity are shown under *Read from the document* on the case overview. A **name that differs** from the typed one (or from the other documents) is flagged in the consistency table, in *Why these are flagged* and on the dashboard ("FSSAI licence (name differs)"). A real FSSAI *receipt* (the FoSCoS payment acknowledgement) has no 14-digit licence number, so its number stays "not provided" rather than being guessed.

Each item has its own **on/off switch** in Settings: turn it off to stop checking it without deleting it.
""",
"14_custom_identity_details": """
# Identity details you switch off or add yourself (TAN, CIN, bank)

No files needed: this is about the typed details.

**How to run:**
1. **Settings → Verification policy → Extra compliance items.** Choose the **TAN** template and press **Add item** (number format `AAAA99999A`: A = letter, 9 = digit, * = either). Under *Identity details* switch **CIN** off. **Save policy.**
2. **New submission:** a **TAN** field now appears under *Additional details* with a live hint, and the **CIN** field is gone.
3. **Load a sample → Kaveri: happy test case (all documents)** (it carries a valid TAN) → Submit. The evidence summary has a **TAN** row with *Format ok* and no CIN row.
4. Change the TAN to something wrong (for example `BAD1`) and submit: the case asks the vendor for **a valid TAN** and the email says so. Leave it empty and submit: it is asked as a required detail.

**Switching a built-in detail off** (GSTIN, PAN, CIN, bank) removes the field from the form and makes the run ignore it everywhere, including in documents: no format check, no registry lookup, no verify link, no required-detail flag. Switching **bank** off also means Finance
is not asked to confirm an account.

**What else can go differently:** a detail marked Optional can be left blank; one set to Indian vendors only is not asked of a foreign vendor; two details with the same name get different keys.
""",
"13_custom_compliance_document": """
# A compliance document you add yourself (Aadhaar)

**Files:** the five Mehta documents plus `mehta_aadhaar_specimen.pdf` (a fictional proprietor, masked number, watermarked SPECIMEN).

**How to run:**
1. **Settings → Verification policy → Extra compliance items.** Choose the **Aadhaar card** template, press **Add item**, and **Save policy**. Optionally switch **Udyam certificate (MSME)** off under *Compliance documents*.
2. **Load a sample → Separate files (Mehta, proprietor)** → Submit. The Required documents list now has **Aadhaar card: Missing**, and the vendor email asks for it.
3. **Load a sample → Mehta with Aadhaar** → Submit. **Aadhaar card: Found** with its file and page.

**Expected:** with Udyam switched off the Udyam row disappears and no MSME check runs. Any document you add is recognised on every page of every upload by the words you list (spaces are ignored, because text
recognition drops them), applies to the vendors you choose, and is requested from the vendor when missing. Personal ID documents carry sensitive numbers: only their presence is recorded, not the number.

**What else can go differently:** a document whose words also appear on other documents (use distinctive words, or require more than one); a scan too blurry for the words to be read (it counts as missing).
""",
"12_bank_account_name_differs": """
# Bank account name differs

**File:** `kaveri_pack_clean.pdf` (fictional Kaveri pack).

**How to run:** **Load a sample → Bank account name differs (Kaveri)**. The typed account holder is a person ("Ravi Kulkarni") while the cheque and the company say Kaveri Precision Components.

**Expected:** the Holder cell is ✗ with both names, "Review the bank account holder name" goes to Finance, and the account is not trusted until they confirm it.
""",
"10_typed_only_no_documents": """
# Problems that need no files

These are run from **Load a sample** and need no documents.

| Sample | Situation | Expected |
|--------|-----------|----------|
| **TCS wrong GSTIN** | GSTIN whose 14th character is C (tax collector) | Flagged instantly, no API credit spent; vendor asked for the regular GSTIN |
| **Zoho look-alike** | A sister company's GSTIN with the right name | PAN inside the GSTIN differs from the PAN given; identifiers outrank names |
| **Zoho duplicate** | Same PAN, GSTIN and bank account as an approved vendor | "Existing vendor found": no new record or code is created. Run **Zoho** first |
| **Zoho new bank account** | New bank details for an approved vendor | Bank change is challenged; confirmed through the contact on file, two approvers |
| **Says US, gives an Indian GSTIN** | Tax ID belongs to another country | Flagged; no Indian source is called |
| **German vendor, French IBAN** | IBAN country differs from claimed country | Flagged |
| **US vendor (EIN)** / **German vendor (VAT + IBAN)** | Vendors outside India | Format checks only; a person confirms the register |

**What else can go differently:** GST registration cancelled or suspended (rejected or pending); composition taxpayer (approved with a payments condition);
registry unreachable (pending, owned by the system, never treated as a pass); PAN on the blocklist (rejected, vendor is not told why).
""",
}

if __name__ == "__main__":
    main()
