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
