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
