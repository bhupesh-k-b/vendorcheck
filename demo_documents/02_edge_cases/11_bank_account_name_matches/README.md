# Bank account name matches the vendor

**File:** `rmc1_munitions_form_filled.pdf`: the vendor form filled with Munitions India Limited's public details. Its bank pages (9 and 10) are in Munitions' own name.

**How to run:** **Load a sample → Munitions: RMC1 form, bank name matches**. For the typed-only happy path on the same company: **Load a sample → Munitions India Limited**
(checked live, finance confirms the bank, a second person approves).

**Expected:** the consistency table shows ✓ under **Account no., IFSC and Holder** on the typed form, the registration form and the bank form. "Munitions India Limited O F Khamaria"
is a unit account of the company, so it matches the legal name. The case still waits on the vendor for the documents not attached (PAN card, GST certificate, address proof, incorporation certificate).

**What else can go differently:** an account in a director's name; a different company's name (the pages are shown as another party's and not used); a joint account.
