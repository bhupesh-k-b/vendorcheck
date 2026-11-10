# VendorCheck: final 5-minute demo script

Target about 4:50 (the cap is 5:00). One happy path, two edge cases and a short Settings segment, all live. Cost: 2 GST credits (Zoho only).
Record from the local server; the deployed link is for submission.

## Before you record
1. `VENDORCHECK_PACING_MS=700 PORT=8765 .venv/bin/python -m vendorcheck`, then open http://127.0.0.1:8765
2. **Settings → Reset data** and confirm, so the dashboard is empty and the Zoho lookup is live on camera.
3. Bottom-left card says **Priya, Procurement**. Never open a key field on camera.
4. Fresh browser window, one tab, zoom 110%, bookmarks hidden, about 1440 wide, Do Not Disturb on.
5. Do not click "Verify PAN via API" (5 credits) or "Check filing history" (1 credit).

## 0:00 – 0:25  Hook (empty dashboard)
"Before a company pays a vendor, someone has to check they're legitimate: complete, consistent and credible. Done by hand it's slow and it's where fraud gets through. VendorCheck takes a vendor submission, typed details and documents, runs it through seven stages, and ends with approved, pending or rejected. Every reason is visible, and the vendor gets a message for anything missing."

## 0:25 – 2:15  Happy path: Zoho (live)
1. **New submission → Load a sample → Zoho.** "Typed details, or documents, or both. Procurement also records category, owner and payment terms."
2. **Submit.** Narrate each stage as it completes:
   - Intake: stores files, opens an immutable version, searches the vendor master for duplicates by PAN, GSTIN and bank account.
   - Read: local OCR and rules read documents; no documents here, so typed values are used.
   - Validate: offline checks, no credits (GSTIN check digit, PAN structure, IFSC). A malformed ID never reaches a paid API.
   - Verify: a real, live GST registry lookup, only for IDs that passed validation.
   - Reconcile: compares typed, document and registry values.
   - Decide: a pure function over the evidence; no hidden state, no override.
   - Communicate: the message, the open tasks and the audit trail.
3. **Pending, waiting on Finance.** "Identity is verified, but no free source proves who owns a bank account, so the system won't guess. One owner, Finance, and a second person must approve."
4. Scroll to **Verify on the official sites**: "Every claim links to the official source."
5. Switch to **Arjun**: Outcome **Confirmed**, How **Called the bank**, note "Account holder matches", **Record**. "He can't approve his own work."
6. Switch to **Neha** → **Approve as second person.** Result **Approved, VND-0001**, and the finished item shows under **Completed**. "One condition: re-check company status on MCA, because there's no free API and the system says so."

## 2:15 – 2:55  Edge case 1: tax ID from another country (zero credits)
Switch to **Priya**. **Load a sample → Says US, gives an Indian GSTIN → Submit.** "The vendor says they're in the United States but typed an Indian GSTIN. The system recognises the shape of the ID, flags it, and never calls an Indian source for a US vendor." Scroll to **Email to the vendor**: "A plain-language email asking for the right ID, and nothing else."

## 2:55 – 4:00  Edge case 2: documents attached, bank name differs (zero credits)
1. **Load a sample → Bank account name differs (Kaveri) → Submit.** While it reads (about 20 s): "A 17-page combined PDF. Each page is identified one by one. Local OCR reads the pages; AI is only a fallback, and it can't invent an identifier."
2. Scroll to **Required documents**, then **Consistency across documents**. Point at the **Holder** column: the typed holder shows ✗ against the bank document's name. "That goes to Finance, and the account isn't trusted until they confirm."
3. Open a document thumbnail: "Pages in another company's name are excluded, never used as this vendor's bank details."
4. "This company is fictional, so the live registry correctly says not found. The system never fakes a registry answer."

## 4:00 – 4:30  Your own policy (Settings, no run)
Open **Settings → Verification policy**. Drag the reading-confidence slider, flip a switch. "Compliance is subjective, so it's configurable." Scroll to **Extra compliance items**, point at **FSSAI licence** and its switch: "Add anything your company requires, a number, a document, or both. It shows up in Required documents, the case overview, the consistency table and the dashboard. If the document states a name or address, that's cross-checked too, and a value only one source shows is marked 'Only source', never a green tick."

## 4:30 – 4:55  Close (dashboard)
"The dashboard keeps history across runs: status, outcome, runs, who's waiting, and tags like 'Missing: FSSAI licence'. Every decision is a deterministic rule with a visible reason. AI reads messy text but never decides. Next: real bank verification, and MCA and Udyam lookups where an API exists."

## If something goes wrong
- A live lookup fails: **Settings → Test GST connection**. Fallback: record the wrong-country and bank-name cases (no credits).
- A run looks stuck: refresh; progress is saved server-side. Wrong role: use the bottom-left card.
- Re-recording the happy path: use **Settings → Reset data** first, otherwise the approved vendor is found as a duplicate.
- Over 5:00: shorten edge case 1 or the Settings segment.

## Optional extras (outside the 5 minutes)
- **Kaveri: happy test case (all documents)**: real OCR reads 14 pages, finance confirms, a second person approves, and it gets a vendor ID flagged **Simulated** (the registry answer is synthetic for a fictional company).
- **Munitions India Limited**: a real company, live-verified, ends Approved.
- **Zoho duplicate** (run after Zoho): "Existing vendor found", no new record.
- **Mehta with FSSAI licence** after **Mehta (separate files)**: the FSSAI document found, name and address cross-checked, number matched.
- Document packs for every scenario are in `demo_documents/` (rebuild with `scripts/build_demo_folders.py`).

## Talking points for "walk us through your decisions"
See `DECISIONS.md`: rules decide and AI only reads; identifiers outrank names; offline checks before paid ones; evidence is labelled by source; two-person rule on bank accounts; immutable versions and an audit trail.
