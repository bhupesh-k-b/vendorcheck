# An item with a number and a document (FSSAI licence)

**Files:** the five Mehta documents plus `mehta_fssai_specimen.pdf` (a specimen licence page, fictional number).

**How to run:**
1. **Settings → Extra compliance items →** template **FSSAI licence → Add item → Save policy.** One item carries both the **number** (14 digits) and the **document** (recognised by "FSSAI"). Optionally switch **Certificate of incorporation** off under *Compliance documents*.
2. **Load a sample → Separate files (Mehta, proprietor)** → Submit. The case shows **FSSAI licence: Missing** in *Required documents*, a **Compliance items** card ("Document missing · Number not provided"), a **Not provided** row and an FSSAI column in the *Consistency table*, and **Missing: FSSAI licence** on the dashboard row.
3. **Load a sample → Mehta with FSSAI licence** → Submit. The document is **Found**, the number is read from the page and compared with the typed one (the consistency table shows ✓ and the evidence summary says *Match*).

Everything a document states is read and compared, not just its number: the **name**, **premises address**, **kind of business**, **reference number**, **date** and validity are shown under *Read from the document* on the case overview. A **name that differs** from the typed one (or from the other documents) is flagged in the consistency table, in *Why these are flagged* and on the dashboard ("FSSAI licence (name differs)"). A real FSSAI *receipt* (the FoSCoS payment acknowledgement) has no 14-digit licence number, so its number stays "not provided" rather than being guessed.

Each item has its own **on/off switch** in Settings: turn it off to stop checking it without deleting it.
