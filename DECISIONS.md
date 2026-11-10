# Decisions and assumptions

## The process, end to end
A vendor submission (typed details, documents, or both) becomes an immutable **version** and runs through seven stages. Each stage is shown live and recorded.

| Stage | What it does |
|---|---|
| **Intake** | Stores files by SHA-256, opens the version, searches the vendor master for duplicates by PAN, GSTIN and bank account. |
| **Read** | Identifies every page (PAN card, GST certificate, cheque, address proof, and any extra documents your policy adds) and extracts identifiers, names and addresses. |
| **Validate** | Offline checks, free: GSTIN check digit, PAN structure, IFSC against the RBI directory, formats for extra items. |
| **Verify** | Live registry lookups (GST), only for identifiers that passed Validate. |
| **Reconcile** | Compares every value across the typed form, each document and the registry, and scores consistency. |
| **Decide** | A pure function over the evidence: Approved, Pending (with one owner per open item) or Rejected. |
| **Communicate** | Writes the vendor message, the open tasks and the audit trail; issues the vendor ID on approval. |

People: Priya (procurement) submits and categorises, Arjun (finance) confirms the bank account, Neha (finance approver) is the second person. Nobody approves their own work.

## Decisions
- **Rules decide, AI only reads.** Local OCR and deterministic rules classify pages and extract identifiers. A language model is an optional fallback for text the rules cannot settle, and a guard rejects any identifier that does not appear in the source text. A model can never approve, reject or invent a value.
- **Identifiers outrank names.** A look-alike company can share a name but never a PAN or GSTIN.
- **Offline before paid.** Validation runs before any paid lookup, so a malformed ID costs nothing.
- **Evidence is labelled by where it came from** (live registry, document, typed, manual, test data) and shown that way. A value only one source shows is marked "Only source" instead of being counted as agreement.
- **Bank ownership is a human check.** No free API proves who owns an account, so Finance confirms it and a second person approves. The system says so instead of guessing.
- **MCA and Udyam are assisted.** There is no free API; the reviewer checks the official site and the result is recorded with a screenshot and a second approval.
- **Policy is data, not code.** Name-match threshold, minimum reading confidence, accepted evidence, which details and documents are required, and extra compliance items (for example an FSSAI licence) are edited in Settings and apply from the next run.
- **Consistency counts missing and wrong documents,** so a pack with the wrong documents cannot score 100.
- **Honest simulation.** A fictional company cannot exist in the real registry. The "simulated" test cases use a clearly labelled synthetic registry answer, are flagged Simulated everywhere, and never mix with real runs. Documents are still read for real.

## Edge cases built in (`demo_documents/02_edge_cases`)
Missing documents, wrong documents attached, another company's bank documents, address-proof mismatch, details inconsistent across documents, a phone photo of a document, a renamed company, US and German vendors, typed-only submission, bank account name matching and differing, a custom compliance document, custom identity details, and an FSSAI licence item.

## Assumptions
- Documents are fictional for fictional companies; real public identifiers are used only for real companies.
- The role switcher stands in for sign-in. There is no authentication.
- One shared policy and one database per server.
- GST lookups use gstinapi.in, which is credit-limited; results are cached for 24 hours.

## Known limits
- **Not for production as is.** No authentication, and anyone who can open the app can change Settings or reset the data.
- **Keys entered in Settings are shared** by everyone using that server instance and live in memory only.
- **The free hosted tier** sleeps when idle and loses data on restart. Document reading (local OCR) is memory-hungry and may need a larger instance.
- Real bank-account verification (penny drop) is wired but not enabled; MCA and Udyam lookups are manual.

## What I would build next
Real bank verification, MCA and Udyam lookups where an API exists, sign-in with roles, persistent storage, and re-verification reminders driven by the vendor master.
