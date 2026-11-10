# VendorCheck

Vendor-onboarding verification. A vendor submits typed details and documents; VendorCheck runs them through seven stages and ends with **Approved**, **Pending** or **Rejected**, with every reason visible and a plain-language message back to the vendor for anything missing.

**Stages:** Intake → Read → Validate → Verify → Reconcile → Decide → Communicate. Each shows live while it runs, and the dashboard keeps history, status and outputs across runs.

## How it decides
- **Rules decide, AI only reads.** Local OCR and deterministic rules identify each page (PAN, GST certificate, cancelled cheque, and so on) and pull out identifiers. A language model is an optional fallback for text the rules cannot settle, and a guard rejects any identifier that is not in the source.
- **Offline checks first.** GSTIN check digit, PAN structure and IFSC (RBI directory) run before any paid lookup.
- **Evidence is labelled.** Live registry, document, typed, manual and test data are kept apart. Test data can never approve a real vendor.
- **Two-person rule** on bank accounts: Finance confirms, a second person approves. Versions are immutable and every step is in the audit trail.
- **Your policy, in Settings.** Name-match threshold, minimum reading confidence, accepted evidence, which identity details and compliance documents are required, and extra items (for example an FSSAI licence) with their own on/off switch.

## Run it
```
make setup        # venv, dependencies, IFSC directory
make dev          # http://127.0.0.1:8000
make test
```
Or with Docker: `docker build -t vendorcheck . && docker run -p 8000:8000 vendorcheck`.

## API keys (optional)
The app works without any key: IFSC checks, offline validation, the test bench and the simulated samples all run locally. For live lookups, open **Settings → Use your own API keys** and paste:
- a GST registry key from [gstinapi.in](https://www.gstinapi.in/register), and/or
- a document-reader key (Gemini, Groq or OpenRouter).

Keys are held in server memory only: never written to disk, never shown again, and removed with one click or on restart. Locally you can instead copy `.env.example` to `.env`. A deployment can hide the form with `ALLOW_USER_KEYS=0`.

## Deploy
`render.yaml` and the `Dockerfile` deploy it on Render (New → Blueprint → this repo). No secrets are in the repo.
The app is a long-running server with a local database and OCR, so it suits a container host rather than serverless functions.

## Demo
`DEMO.md` has the five-minute walkthrough. `demo_documents/` holds document packs by scenario, rebuilt with `python scripts/build_demo_folders.py`. The **Test bench** runs every scenario with zero credits.

## Assumptions
- Documents are fictional for fictional companies; real public identifiers are used only for real companies.
- The role switcher (Priya, Arjun, Neha) stands in for sign-in.
- No free API proves who owns a bank account, so bank ownership is confirmed by two people. MCA and Udyam have no free API, so the reviewer checks the official site and the system says so.
