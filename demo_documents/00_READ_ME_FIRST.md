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
