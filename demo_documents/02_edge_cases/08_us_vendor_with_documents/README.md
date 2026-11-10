# US vendor with documents

**File:** `lakeview_us_pack.pdf`: W-9, bank confirmation letter and articles of organization (fictional US company).

**How to run:** **Load a sample → US vendor with documents (Lakeview)**. For the problem variant: **Says US, documents US, but gives an Indian ID**.

**Expected:** no India-only checks (no GSTIN or PAN verification). The EIN and routing number are checked for shape and checksum only; a person confirms the
official register and finance confirms the bank. In the variant, an Indian GSTIN typed for a US vendor is flagged as an ID that belongs to another country.

**What else can go differently:** documents from several countries in one pack; a phone code or address that points to another country.
