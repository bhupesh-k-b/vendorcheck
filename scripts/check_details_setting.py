"""End to end: add TAN, switch CIN off, check the form, run a valid and an invalid TAN, restore."""
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)


def submit_sample(page, key, tan=None):
    page.goto(BASE + "/new")
    page.wait_for_load_state("networkidle")
    page.click("#sample-menu-btn")
    page.click(f'[data-example="{key}"]')
    page.wait_for_timeout(500)
    if tan is not None:
        page.fill("#f-x_tan", tan)
        page.wait_for_timeout(200)
        print("   live hint:", page.inner_text("#f-x_tan >> xpath=../p").strip())
    page.click("#submit-btn")
    page.wait_for_url(re.compile(r".*/runs/\d+"))
    page.wait_for_selector("#run-done", state="attached", timeout=300000)
    page.wait_for_timeout(600)


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1000})
    page.on("pageerror", lambda e: print("JS ERROR", e))
    page.goto(BASE + "/settings")
    page.wait_for_load_state("networkidle")
    page.select_option('select[aria-label="Start from a detail template"]', "tan")
    page.click("#add-detail")
    page.locator('label:has-text("CIN") .switch').first.click()
    page.locator("#custom-details").screenshot(path=str(OUT / "details-settings.png"))
    page.click("#policy-save")
    page.wait_for_load_state("networkidle")
    print("saved:", page.inner_text("[role=status]")[:80], "| cin switch on:", page.is_checked('input[name="detail__cin"]'))

    page.goto(BASE + "/new")
    page.wait_for_load_state("networkidle")
    print("form: TAN field:", page.locator('input[name="x_tan"]').count(), "| CIN field:", page.locator('input[name="cin"]').count(), "| GSTIN field:", page.locator('input[name="gstin"]').count())

    print("\n-- valid TAN")
    submit_sample(page, "happy_documents", tan="PNEK12345E")
    print("  ", page.inner_text("h2:has-text('Pending'), h2:has-text('Approved')")[:90])
    page.evaluate("document.querySelectorAll('details').forEach(d => { if (d.querySelector('#ev-h')) d.open = true })")
    ev = page.locator("details:has(#ev-h)").inner_text()
    print("   evidence has TAN row:", bool(re.search(r"TAN\s+PNEK12345E", re.sub(r"[ \t]+", " ", ev))), "| CIN row:", "CIN" in ev)

    print("\n-- invalid TAN")
    submit_sample(page, "happy_documents", tan="BAD1")
    top = page.inner_text("#run")
    print("  ", page.inner_text("h2:has-text('Pending'), h2:has-text('Approved')")[:100])
    print("   asks for a valid TAN:", "valid TAN" in top, "| vendor email mentions TAN:", "TAN" in page.input_value("#email-panel textarea"))
    page.screenshot(path=str(OUT / "details-invalid-tan.png"))

    print("\n-- restore")
    page.goto(BASE + "/settings")
    page.wait_for_load_state("networkidle")
    page.click('button[aria-label="Remove this detail"]')
    page.locator('label:has-text("CIN") .switch').first.click()
    page.click("#policy-save")
    page.wait_for_load_state("networkidle")
    print("   custom details:", page.locator('input[name="cdetail_label"]').count(), "| cin on:", page.is_checked('input[name="detail__cin"]'))
    b.close()
