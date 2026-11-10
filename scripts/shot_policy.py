"""Exercise the Settings policy form in a browser: screenshot, change the threshold and a switch, save, check, then put it back."""
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1000})
    page.on("pageerror", lambda e: print("JS ERROR", e))
    page.goto(BASE + "/settings")
    page.wait_for_load_state("networkidle")
    page.locator("#policy").screenshot(path=str(OUT / "policy-before.png"))
    orig = page.input_value('input[name="name_match_threshold"]')
    print("threshold before:", orig)
    page.locator('input[type="range"]').fill("80")
    page.locator('label:has-text("A person must confirm every company rename") .switch').click()
    page.click("#policy-save")
    page.wait_for_load_state("networkidle")
    print("flash:", page.inner_text("[role=status]")[:120])
    print("threshold after:", page.input_value('input[name="name_match_threshold"]'), "| rename switch:", page.is_checked('input[name="rename_requires_person"]'))
    print("last changed:", page.inner_text("#policy span.rounded-full")[:80])
    page.locator("#policy").screenshot(path=str(OUT / "policy-after.png"))
    # put it back
    page.locator('input[type="range"]').fill(orig)
    page.locator('label:has-text("A person must confirm every company rename") .switch').click()
    page.click("#policy-save")
    page.wait_for_load_state("networkidle")
    print("restored:", page.input_value('input[name="name_match_threshold"]'), page.is_checked('input[name="rename_requires_person"]'))
    b.close()
