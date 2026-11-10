# German vendor with documents

**File:** `rheinland_eu_pack.pdf`: VAT certificate, IBAN bank letter and commercial-register extract (fictional German GmbH).

**How to run:** **Load a sample → German vendor with documents (Rheinland)**. For the problem variant: **German vendor, French IBAN**.

**Expected:** VAT number shape, IBAN check digits and the SWIFT country are checked. No GSTIN is expected anywhere. In the variant, the IBAN belongs to France while
the vendor says Germany, so it is flagged.

**What else can go differently:** a VAT number for a different EU country; an IBAN that fails its check digits.
