# 02 Edge cases: what can go differently

| Folder | Situation | Expected outcome |
|--------|-----------|------------------|
| `01_missing_documents` | Vendor skips PAN card, cancelled cheque and address proof | Pending on the vendor, email lists exactly what is missing |
| `02_wrong_documents_attached` | Brochure, unrelated invoice, someone else's PAN card | Pending on the vendor, each file explained |
| `03_other_companys_bank_documents` | Bank documents belong to a different company | Those pages are excluded, vendor asked for their own |
| `04_address_proof_mismatch` | Electricity bill shows a different address from the GST registration | Address mismatch flagged |
| `05_inconsistent_details_across_documents` | PAN digits swapped on the form, other planted differences | Conflicts shown in the consistency table, vendor asked to confirm |
| `06_phone_photo_of_a_document` | A photographed PAN card instead of a clean scan | Read with lower confidence; key numbers read twice and confirmed |
| `07_company_renamed` | Company changed its legal name | Approved with an explanation when the filing shows the rename |
| `08_us_vendor_with_documents` | US company, W-9 and bank letter | No India checks; person confirms the register; Indian ID typed instead is flagged |
| `09_german_vendor_with_documents` | German company, VAT certificate, IBAN | VAT shape and IBAN checked; France IBAN for a German company is flagged |
| `10_typed_only_no_documents` | Problems that need no files | See its README (wrong GSTIN type, look-alike, duplicate vendor, bank change, wrong country ID) |
| `11_bank_account_name_matches` | The name on the bank account is the vendor's own (Munitions India Limited) | Holder agrees across the typed form, the bank form and the legal name; the unit account counts as the company's |
| `13_custom_compliance_document` | A document your company needs (Aadhaar) is added in Settings; one it does not (Udyam) is switched off | Shown as Found or Missing in the full case, requested in the vendor email |
| `15_fssai_licence_item` | An item with both a number and a document (FSSAI licence) is added | Number and document shown as found or missing in the checklist, summary card, consistency table and dashboard |
| `14_custom_identity_details` | An identity detail is added (TAN) and one is switched off (CIN) | New field on the form, format-checked live and on submit; the switched-off one disappears everywhere |
| `12_bank_account_name_differs` | The typed account holder is a person, the bank document says the company | Holder flagged in the consistency table; finance reviews |
