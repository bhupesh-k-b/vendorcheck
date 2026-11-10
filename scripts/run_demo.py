"""Drives DEMO.md end to end in a real browser (Playwright) and saves screenshots to screenshots/demo/.

    .venv/bin/python scripts/run_demo.py                 # full demo (needs GSTINAPI_KEY and GEMINI_API_KEY in .env)
    .venv/bin/python scripts/run_demo.py --offline       # only what needs no keys
    .venv/bin/python scripts/run_demo.py --photo my.jpg  # also upload a phone photo of the hand-filled form (step 6)
    BASE=http://127.0.0.1:8000 to point at another server (default: starts nothing; run `make dev` first)

It RESETS the demo data first (Settings → Reset demo data) so every run starts clean."""
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE = os.getenv("BASE", "http://127.0.0.1:8000")
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "screenshots" / "demo"
OUT.mkdir(parents=True, exist_ok=True)
OFFLINE = "--offline" in sys.argv
PHOTO = sys.argv[sys.argv.index("--photo") + 1] if "--photo" in sys.argv else None
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


def shot(page: Page, name: str, full=True):
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)


def role(page: Page, who: str):
    page.select_option("#role", who)
    page.wait_for_load_state("networkidle")


def wait_run(page: Page, timeout=180000):
    page.wait_for_selector("#run-done", state="attached", timeout=timeout)
    page.wait_for_timeout(400)


def text(page: Page) -> str:
    return page.inner_text("body")


def submit_example(page: Page, key: str, sample_button: str | None = None):
    page.goto(BASE + "/new")
    page.wait_for_load_state("networkidle")
    if sample_button:
        page.click(f'[data-sample="{sample_button}"]')
    else:
        page.click(f'[data-example="{key}"]')
    page.wait_for_timeout(500)
    page.click("#submit-btn")
    page.wait_for_url(re.compile(r".*/runs/\d+"))
    wait_run(page)


def case_id(page: Page) -> str:
    href = page.get_attribute('a[href^="/cases/"]', "href")
    return re.search(r"/cases/(\d+)", href).group(1)


def finance_confirm(page: Page, note: str, outcome="confirmed", method="Called the bank"):
    """Arjun records how he confirmed; Neha approves as the second person (R22)."""
    role(page, "arjun")
    page.select_option('form[action$="/resolve"] select[name=outcome]', outcome)
    page.select_option('form[action$="/resolve"] select[name=method]', method)
    page.fill('form[action$="/resolve"] input[name=note]', note)
    page.click('form[action$="/resolve"] button')
    page.wait_for_load_state("networkidle")
    check("R22: resolver cannot approve (no approve button for Arjun)", page.locator('button[value=approve]').count() == 0)
    role(page, "neha")
    page.click('button[name=decision][value=approve]')
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)


def vendor_fix(page: Page, ctx, values: dict):
    link = page.get_attribute('a[href^="/v/"]', "href")
    vp = ctx.new_page()
    vp.goto(BASE + link)
    check("vendor portal shows a numbered list", vp.locator("ol li").count() >= 1)
    for k, v in values.items():
        vp.fill(f'input[name="{k}"]', v)
    shot(vp, "vendor-portal")
    vp.click("button:has-text('Submit')")
    vp.wait_for_load_state("networkidle")
    vp.close()


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        page.on("pageerror", lambda e: check("no JS errors", False, str(e)))

        # ---- reset ----
        page.goto(BASE + "/settings")
        page.click("#reset-btn")
        page.wait_for_load_state("networkidle")
        page.goto(BASE + "/settings")
        shot(page, "00-settings")

        if not OFFLINE:
            # ---- 1. Happy path: Zoho ----
            submit_example(page, "zoho")
            shot(page, "01-zoho-pending")
            t = text(page)
            check("1 Zoho: GST fetched live, name on record", "ZOHO CORPORATION PRIVATE LIMITED" in t and "live" in t)
            check("1 Zoho: ends Pending, waiting on finance to confirm the bank account", "Pending" in t and "confirm the bank account" in t)
            finance_confirm(page, "Called HDFC branch; holder matches")
            shot(page, "01-zoho-approved")
            check("1 Zoho: Approved with a vendor master record", "Approved" in text(page) and "VND-0001" in text(page))

        # ---- 2. E3 look-alike ----
        submit_example(page, "zoho_lookalike")
        shot(page, "02-e3-pending")
        t = text(page)
        check("2 E3: R08 flags the PAN inside the GSTIN", "R08" in t and "PAN inside the GSTIN" in t)
        check("2 E3: Pending, waiting on vendor", "Pending" in t and "vendor" in t.lower())
        check("2 E3: vendor message shown, no other company named", "Message to the vendor" in t and "Payment Technologies" not in t)
        if not OFFLINE:
            vendor_fix(page, ctx, {"gstin": "33AAACZ4322M1ZA", "pan": "AAACZ4322M"})
            page.goto(f"{BASE}/cases/{case_id(page)}")
            wait_run(page)
            shot(page, "02-e3-v2")
            check("2 E3: version 2 ran and passed identity checks", "Version 2" in text(page) and "R11" in text(page))

        # ---- 3. E2 wrong type of GSTIN ----
        submit_example(page, "tcs")
        shot(page, "03-e2-pending")
        t = text(page)
        check("3 E2: R06 flags the tax-collector GSTIN instantly", "R06" in t and "tax-collector" in t)
        check("3 E2: no API credit spent (GST skipped)", "no API credit spent" in t.lower() or "Skipped, no API credit" in t)
        if not OFFLINE:
            vendor_fix(page, ctx, {"gstin": "24AAACR4849R1ZR"})
            page.goto(f"{BASE}/cases/{case_id(page)}")
            wait_run(page)
            shot(page, "03-e2-v2")
            check("3 E2: regular Gujarat GSTIN verifies live", "Gujarat" in text(page))

        # ---- R20: simulated outage ----
        page.goto(BASE + "/settings")
        page.click("#outage-btn")
        page.wait_for_load_state("networkidle")
        submit_example(page, "infosys")
        shot(page, "03b-r20-simulated-outage")
        t = text(page)
        check("R20: simulated outage => Pending, owned by the system, never a pass", "SIMULATED" in t and "Pending" in t and "never treated as a pass" in t)
        page.goto(BASE + "/settings")
        page.click("#outage-btn")
        page.wait_for_load_state("networkidle")

        if not OFFLINE:
            # ---- 4. E1: Eternal ----
            submit_example(page, "eternal")
            if "Declared name matches the GST legal name" in text(page):     # GST already says ETERNAL: declare the old name instead
                submit_example(page, "eternal_old")
            shot(page, "04-e1-eternal")
            t = text(page)
            check("4 E1: rename explained from the NSE filing", "passed with an explanation" in t and "renamed" in t)
            finance_confirm(page, "Cheque seen")
            shot(page, "04-e1-approved")
            check("4 E1: Approved with an explanation", "Approved" in text(page) and "explanation" in text(page).lower())

            # ---- 5. E4: bank change on approved Zoho ----
            submit_example(page, "zoho_bank_change")
            shot(page, "05-e4-pending")
            t = text(page)
            check("5 E4: R18 fires, Pending on finance", "R18" in t and "Pending" in t)
            finance_confirm(page, "contact on file says this is not our account", outcome="reject", method="Called the contact on file")
            shot(page, "05-e4-rejected")
            check("5 E4: change Rejected", "Rejected" in text(page))
            page.goto(BASE + "/vendors/VND-0001")
            t = text(page)
            check("5 E4: previously approved account stays active", "1772" in t and "active" in t and "1191" not in t)

            # ---- 6. Any-format input ----
            submit_example(page, "", sample_button="infosys")
            shot(page, "06-typed-pdf")
            check("6 typed PDF: fields read, Infosys verified", "INFOSYS LIMITED" in text(page).upper() and "R11" in text(page))
            if PHOTO:
                page.goto(BASE + "/new")
                page.set_input_files('input[name="files"]', PHOTO)
                page.click("#submit-btn")
                page.wait_for_url(re.compile(r".*/runs/\d+"))
                wait_run(page)
                shot(page, "06-photo")
                t = text(page)
                check("6 photo: fields extracted; low-confidence digits go to the vendor, not guessed", "R05" in t or "R11" in t)

        # ---- 7. Dashboard ----
        page.goto(BASE + "/")
        shot(page, "07-dashboard")
        t = text(page)
        check("7 dashboard lists cases with status, waiting on, versions, time to decision", "waiting on" in t.lower() and "versions" in t.lower() and "time to decision" in t.lower())
        page.click("tbody tr:first-child")
        page.wait_for_load_state("networkidle")
        page.click("a[role=tab]:has-text('Audit log')")
        shot(page, "07-audit")
        check("7 row opens the case with its audit log", "Audit log" in text(page) and "submission" in text(page))

        # ---- bench ----
        page.goto(BASE + "/bench")
        page.click("#bench-run")
        page.wait_for_load_state("networkidle")
        shot(page, "08-bench")
        check("bench: all scenarios green", "All green" in text(page))
        browser.close()

    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
