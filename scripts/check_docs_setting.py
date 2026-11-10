"""End to end: add Aadhaar and switch off Udyam in Settings, submit Mehta without and with the Aadhaar page, then restore the settings."""
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)


def run_sample(page, key):
    page.goto(BASE + "/new")
    page.wait_for_load_state("networkidle")
    page.click("#sample-menu-btn")
    page.click(f'[data-example="{key}"]')
    page.wait_for_timeout(400)
    page.click("#submit-btn")
    page.wait_for_url(re.compile(r".*/runs/\d+"))
    page.wait_for_selector("#run-done", state="attached", timeout=300000)
    page.wait_for_timeout(700)


def checklist(page):
    rows = []
    for li in page.locator("#checklist ul > li").all():
        t = re.sub(r"\s+", " ", li.inner_text())
        rows.append(t[:110])
    return rows


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1000})
    page.on("pageerror", lambda e: print("JS ERROR", e))
    # 1. Settings: add Aadhaar from the template, switch off Udyam
    page.goto(BASE + "/settings")
    page.wait_for_load_state("networkidle")
    page.select_option('select[aria-label="Start from a template"]', "aadhaar_card")
    page.click("#add-doc")
    page.locator('label:has-text("Udyam certificate") .switch').click()
    page.locator("#custom-docs").screenshot(path=str(OUT / "docs-settings-custom.png"))
    page.click("#policy-save")
    page.wait_for_load_state("networkidle")
    print("saved:", page.inner_text("[role=status]")[:90])
    print("custom rows after save:", page.locator('input[name="custom_label"]').count(), "| udyam switch on:", page.is_checked('input[name="doc__udyam_certificate"]'))

    # 2. Mehta WITHOUT the Aadhaar page
    run_sample(page, "mehta_separate")
    print("\n-- Mehta without Aadhaar:", page.inner_text("h2:has-text('Pending'), h2:has-text('Approved')")[:100])
    for r in checklist(page):
        print("  ", r)
    print("email asks for Aadhaar:", "Aadhaar" in page.inner_text("#email-panel"))
    page.locator("#checklist").screenshot(path=str(OUT / "docs-without-aadhaar.png"))

    # 3. Mehta WITH the Aadhaar page
    run_sample(page, "mehta_aadhaar")
    print("\n-- Mehta with Aadhaar:", page.inner_text("h2:has-text('Pending'), h2:has-text('Approved')")[:100])
    for r in checklist(page):
        print("  ", r)
    page.locator("#checklist").screenshot(path=str(OUT / "docs-with-aadhaar.png"))

    # 4. restore: remove the custom document, switch Udyam back on
    page.goto(BASE + "/settings")
    page.wait_for_load_state("networkidle")
    page.click('button[aria-label="Remove this document"]')
    page.locator('label:has-text("Udyam certificate") .switch').click()
    page.click("#policy-save")
    page.wait_for_load_state("networkidle")
    print("\nrestored: custom rows", page.locator('input[name="custom_label"]').count(), "| udyam on:", page.is_checked('input[name="doc__udyam_certificate"]'))
    b.close()
