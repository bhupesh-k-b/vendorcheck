# Wrong documents attached

**File:** `orchid_wrong_documents.pdf`: a brochure, an unrelated invoice, someone else's PAN card and a bill.

**How to run:** **Load a sample → Wrong documents attached (Orchid)**.

**Expected:** pages are identified one by one. The brochure and invoice are recognised as not onboarding documents; the PAN card belongs to
another person, so it is not used. Required documents show as missing and the vendor is asked to send the right ones.

**What else can go differently:** a correct document for the wrong year or wrong entity; the same file uploaded twice (stored once by its hash).
