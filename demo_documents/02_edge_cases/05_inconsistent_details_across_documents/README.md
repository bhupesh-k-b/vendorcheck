# Inconsistent details across documents

**File:** `kaveri_pack_messy.pdf`: the same pack as the happy path with planted problems: the PAN on the form has two digits swapped, and other values differ between documents.

**How to run:** **Load a sample → Document pack: inconsistent**.

**Expected:** the consistency table shows ✗ where documents disagree, with a "Why these are flagged" list. The score drops and the vendor is asked to confirm the values.

**What else can go differently:** legal name spelled differently on the cheque; account holder differs from the vendor; IFSC does not exist.
