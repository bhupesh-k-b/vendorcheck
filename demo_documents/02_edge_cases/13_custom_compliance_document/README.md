# A compliance document you add yourself (Aadhaar)

**Files:** the five Mehta documents plus `mehta_aadhaar_specimen.pdf` (a fictional proprietor, masked number, watermarked SPECIMEN).

**How to run:**
1. **Settings → Verification policy → Extra compliance items.** Choose the **Aadhaar card** template, press **Add item**, and **Save policy**. Optionally switch **Udyam certificate (MSME)** off under *Compliance documents*.
2. **Load a sample → Separate files (Mehta, proprietor)** → Submit. The Required documents list now has **Aadhaar card: Missing**, and the vendor email asks for it.
3. **Load a sample → Mehta with Aadhaar** → Submit. **Aadhaar card: Found** with its file and page.

**Expected:** with Udyam switched off the Udyam row disappears and no MSME check runs. Any document you add is recognised on every page of every upload by the words you list (spaces are ignored, because text
recognition drops them), applies to the vendors you choose, and is requested from the vendor when missing. Personal ID documents carry sensitive numbers: only their presence is recorded, not the number.

**What else can go differently:** a document whose words also appear on other documents (use distinctive words, or require more than one); a scan too blurry for the words to be read (it counts as missing).
