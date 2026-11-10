# Another company's bank documents inside the pack

**File:** `rmc1_infosys_form_filled.pdf`: the 11-page vendor form filled with Infosys's public details. Its bank pages (9 and 10) name a different
company as account holder.

**How to run:** **Load a sample → RMC1 form: Infosys (original details)**.

**Expected:** the bank pages are recognised as another party's, shown with a warning in the document viewer, and **not used** as the vendor's bank
details. Because no bank document in the vendor's own name exists, the vendor is asked to send one. The other company is never named in the email.

**What else can go differently:** a cheque in the name of a director rather than the company; a joint account; a bank letter older than expected.
