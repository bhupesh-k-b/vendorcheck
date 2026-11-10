# VendorCheck: final 5-minute demo script

Target length 4:30 to 4:50 (the cap is 5:00). One happy path and two edge cases, all live. Total cost: 2 of the 3 remaining GST credits.

## Before you record

1. Server: `VENDORCHECK_PACING_MS=700 PORT=8765 .venv/bin/python -m vendorcheck`, then open http://127.0.0.1:8765
2. **Settings → Reset data** (confirm). This empties the dashboard and clears cached registry answers, so the Zoho lookup is live on camera.
3. Bottom-left user card says **Priya, Procurement**. Settings page shows every connection green (do not show anything with keys).
4. Browser: a fresh window, one tab, zoom 110%, bookmarks bar hidden, window about 1440 wide. macOS Do Not Disturb on, other apps closed.
5. Do **not** click "Verify PAN via API" (5 credits) or "Check filing history" (1 credit).
6. Rehearse the zero-credit parts as often as you like: the wrong-country case, the test bench, navigation. A full live rehearsal costs 2 credits, so top up credits first if you want one.
7. Start the recorder, take a breath, begin.

## Timeline

### 0:00 – 0:25  Hook (empty dashboard)
Say: "Before a company pays a vendor, someone has to check they're legitimate: complete, consistent and credible. Done by hand it's slow and it's where fraud gets through. VendorCheck takes a vendor submission, typed details and documents, runs it through seven stages, and ends with approved, pending or rejected, with every reason visible and a message back to the vendor for anything missing."
Point at the sidebar and the empty dashboard.

### 0:25 – 2:35  Happy path: Zoho (live)
1. **New submission → Load a sample → Zoho**. Scroll the form. Say: "Typed details, or documents, or both. Procurement also records category, owner and payment terms."
2. **Submit for verification.** Let the stages tick for two seconds, then narrate each as it completes:
   - **Intake:** "Stores files, opens an immutable version, searches the vendor master for duplicates by PAN, GSTIN and bank account."
   - **Read:** "Local text recognition and deterministic extraction read documents. No documents here, so typed values are used."
   - **Validate:** "Offline checks, no credits: GSTIN check digit, PAN structure, IFSC in the RBI directory. A malformed ID never reaches a paid API."
   - **Verify:** "A real, live GST registry lookup, only for identifiers that passed validation."
   - **Reconcile:** "Compares typed, document and registry values."
   - **Decide:** "A pure function over the evidence. No hidden state, no override."
   - **Communicate:** "Writes the message, the open tasks and the audit trail."
3. Result: **Pending, waiting on finance to confirm the bank account.** Say: "Identity is verified, but no free source proves who owns a bank account, so the system won't guess. One owner, Finance, and a second person must approve."
4. Scroll once: Next steps, Verify on the official sites. Say: "Every claim links to the official source so a human can check it."
5. Bottom-left user card → **Arjun**. Outcome **Confirmed**, How **Called the bank**, note "Account holder matches", **Record**. Say: "He can't approve his own work."
6. Switch to **Neha** → **Approve as second person.** Result **Approved, VND-0001**. Say: "One condition: re-check company status on MCA, because there's no free API and the system says so instead of pretending."

### 2:35 – 3:25  Edge case 1: the tax ID belongs to another country (zero credits)
1. Switch to **Priya**. **New submission → Load a sample → Says US, gives an Indian GSTIN → Submit.**
2. Say: "The vendor says they're in the United States but typed an Indian GSTIN. The system recognises the shape of the ID, flags it, and never calls an Indian source for a US vendor."
3. Point at the Next-steps card ("This looks like an Indian GSTIN, but the vendor says it is based in United States") and scroll to **Email to the vendor**. Say: "The vendor gets a plain-language email asking for the right ID. Nothing else."

### 3:25 – 4:35  Edge case 2: documents attached, but the bank account name differs
1. **New submission → Load a sample → Bank account name differs (Kaveri) → Submit.**
2. While it reads (about 20 seconds) say: "Now real documents: a 17-page combined PDF. Each page is identified one by one, so a PAN card or cheque inside one PDF is found. Local OCR reads the pages; AI is only used for tricky text, and it can't invent an identifier."
3. Result: scroll to **Required documents** ("found by page") and **Consistency across documents**. Point at the **Holder** column: the typed holder "Ravi Kulkarni" ✗ against the bank document's company name. Say: "The name on the submission doesn't match the name on the bank account. That goes to Finance, and the account isn't trusted until they confirm."
4. Click a document thumbnail to open the page viewer. Say: "Pages in another company's name are excluded and shown as another party's, never used as this vendor's bank details."
5. Say: "This company is fictional, so the live registry correctly says not found. The system never fakes a registry answer."

### 4:35 – 5:00  Close (dashboard)
Open the dashboard. Say: "The dashboard keeps history across runs: status, outcome, how many runs, who's waiting, and tags when documents or the typed form are missing. Every decision is a deterministic rule with a visible reason. AI reads messy text but never decides. Thresholds and accepted evidence live in Settings, so a company can set its own policy. What I'd build next: real bank verification, and the MCA and Udyam lookups where an API exists."

## If something goes wrong
- A live lookup fails: **Settings → Test GST connection**. Fallback: **Test bench → Run all scenarios** (22 scenarios, zero credits, about a second) and narrate those.
- A run looks stuck: refresh. Progress is saved server-side.
- Wrong role selected: use the bottom-left user card.
- Only one live take is affordable: do not reset again. If the Zoho take fails, you have 1 credit left.

## Optional extras (outside the 5 minutes, for the live interview)
- **Munitions India Limited** sample: a real company, live-verified, ends Approved. **Munitions: RMC1 form, bank name matches**: the Holder column all ✓.
- **Happy test case with all documents** (Load a sample → "Kaveri: happy test case (all documents)"): real OCR reads 14 pages, all five required documents found, consistency Strong, finance confirms
  and a second person approves: Approved, labelled **Simulated** (the registry answer is synthetic for a fictional company; never written to the vendor master). Same flow without a browser: Test bench scenario H2.
- **Zoho duplicate** (run after Zoho): "Existing vendor found", no new record or code.
- **TCS wrong GSTIN**: tax-collector GSTIN flagged instantly, no credit spent.
- **Settings → Verification policy**: change the name-match threshold, the minimum reading confidence or accepted evidence live.
- **FSSAI licence required together with other things** (Test bench, scenarios **F1 to F4**): the FSSAI licence number and certificate plus a TAN, on top of every standard detail and document.
  F1 everything provided, approved by two people; F2 number and TAN left out, asked of the vendor; F3 a wrong-format number; F4 the certificate missing from an otherwise complete document set.
- **Extra compliance items** (Settings): add anything your company needs, as a **number** (a form field with a format like `AAAA99999A`), a **document** (recognised by words on the page), or both, for example **FSSAI licence**.
  Each has its own on/off switch. It appears as found or missing in Required documents, a Compliance items card on the case overview, the consistency table (an FSSAI column and a "Not provided" row) and the dashboard
  ("Missing: FSSAI licence"). Everything the document states (name, address, kind of business, reference no., dates) is read and compared with the other documents, and a name that differs is flagged. Load **Mehta (separate files)** to see it missing, then **Mehta with FSSAI licence** to see the document found and the number matched. Folder `15_fssai_licence_item`.
- **Identity details** (Settings): switch off GSTIN, PAN, CIN or bank details. They disappear from the form and are ignored everywhere. Folder `14_custom_identity_details` has the steps for adding a TAN.
- **Compliance documents** (Settings): add a document your company needs (for example **Aadhaar card** from the template) and switch off one you don't (for example Udyam). Then **Load a sample → Separate files (Mehta)**:
  the new document shows **Missing** and the vendor email asks for it; **Mehta with Aadhaar** shows it **Found**. Folder `13_custom_compliance_document` has the files and steps.

## Talking points for "walk us through your decisions"
- **Deterministic rules decide; AI only reads.** Text recognition and rules do the work; the language model only cleans up hard-to-read text and can't introduce an identifier that isn't in the source.
- **Identifiers outrank names.** A look-alike company can share a name, never a PAN.
- **Offline checks before paid ones.** Validate before Verify, so bad IDs cost nothing.
- **Honesty about evidence.** Live, manual (second person approves), document and test data are kept apart. Test data can never approve a real vendor.
- **Two-person rule** on bank accounts. Versions are immutable. A full audit trail.
- **Assumptions:** fictional documents for fictional companies; real public identifiers only for real companies; the role switcher stands in for sign-in.

## Rebuild the sample documents
`demo_documents/` holds document packs by scenario. Rebuild with `.venv/bin/python scripts/build_demo_folders.py`.
