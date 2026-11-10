# 01 Happy path: a complete, consistent document set

**Vendor:** Kaveri Precision Components Private Limited (fictional, MSME, company). All six required documents, details agree everywhere.

| Folder | What it is | Sample entry |
|--------|------------|--------------|
| `A_separate_files/` | The seven documents as separate files | upload all seven files |
| `B_one_combined_pdf/` | The same documents in one 17-page PDF | **Load a sample → One PDF with everything (Kaveri, MSME)** |

Files in `A_separate_files/`: registration form (11 pages), PAN card, GST registration certificate, cancelled cheque,
certificate of incorporation, address proof (electricity bill), Udyam certificate.

## What you should see

- The required-documents table shows all six documents **Found**, with the page each was found on (combined PDF) or the file name (separate files).
- Consistency across documents scores **100 / Strong**: legal name, PAN, GSTIN, CIN, bank account and IFSC agree across every document.
- The document viewer beside the results shows each page with what was read from it.
- Offline checks pass: GSTIN check digit, PAN structure, IFSC found in the RBI list.

## Why this company ends "Pending" and not "Approved"

Approval needs the GST registry to confirm the GSTIN. Kaveri is fictional, so the registry correctly answers **not found**, and the
case waits on the vendor. VendorCheck never fakes a registry answer, and sample or recorded data can never approve a real vendor.

To see the **complete flow with every document attached ending in Approved**, use `C_happy_test_case/` : **Load a sample → Happy test case: typed details and all documents**.
Typed details plus the registration form, PAN card, GST certificate, cancelled cheque, certificate of incorporation and address proof. All five required documents are found,
consistency is 100 (Strong), it waits on Finance for the bank, and two people approve. The documents are read for real (14 pages). It is labelled **Simulated** because the
fictional company's registry answer is synthetic, and it is never written to the vendor master. The test bench scenario **H2** covers the same flow without a browser.

For a **live approved** case use the real-company example (typed details, checked live): **Load a sample → Zoho**, then finance confirms
the bank account and a second person approves. To see an approval with documents, upload a real company's own documents (with its
permission) into this folder structure: the checklist and consistency view work the same way.
