"""Exercise the reading-confidence setting end to end in a browser: read a scanned pack, see page confidence, raise the minimum, re-run, restore."""
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)


def set_minimum(page, value):
    page.goto(BASE + "/settings")
    page.wait_for_load_state("networkidle")
    page.locator('input[aria-label="Minimum reading confidence"]').fill(str(value))
    page.click("#policy-save")
    page.wait_for_load_state("networkidle")
    return page.input_value('input[name="read_confidence"]')


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1000})
    page.on("pageerror", lambda e: print("JS ERROR", e))
    print("minimum now:", set_minimum(page, 80))
    page.goto(BASE + "/new")
    page.wait_for_load_state("networkidle")
    page.click("#sample-menu-btn")
    page.click('[data-example="happy_documents"]')
    page.wait_for_timeout(400)
    page.click("#submit-btn")
    page.wait_for_url(re.compile(r".*/runs/\d+"))
    page.wait_for_selector("#run-done", state="attached", timeout=240000)
    page.wait_for_timeout(600)
    run_url = page.url
    print("status at 80%:", page.inner_text("h2:has-text('Pending'), h2:has-text('Approved')")[:90])
    # per-page confidence in the viewer (the PAN card is a scanned page)
    thumbs = page.locator("#docs-panel button:has(img)")
    print("pages:", thumbs.count())
    thumbs.nth(9).click()
    page.wait_for_timeout(500)
    box = page.locator("#docs-panel [role=dialog]")
    print("viewer confidence:", re.sub(r"\s+", " ", box.locator("text=Reading confidence").locator("..").inner_text())[:120])
    page.screenshot(path=str(OUT / "confidence-viewer.png"))
    page.keyboard.press("Escape")
    # raise the minimum, re-run
    print("minimum now:", set_minimum(page, 99))
    page.goto(run_url)
    page.wait_for_load_state("networkidle")
    page.click("button:has-text('Re-run all checks')")
    page.wait_for_load_state("networkidle")
    page.goto(run_url.replace(re.search(r"/runs/\d+", run_url).group(0), "/cases/1")) if False else None
    case_href = page.get_attribute('a:has-text("Open submission")', "href")
    page.goto(BASE + case_href)
    page.wait_for_selector("#run-done", state="attached", timeout=240000)
    page.wait_for_timeout(600)
    txt = page.inner_text("#run")
    print("status at 99%:", page.inner_text("h2:has-text('Pending'), h2:has-text('Approved')")[:100])
    print("mentions minimum:", bool(re.search(r"below the 99% minimum", txt)), "| low-confidence note:", "Low reading confidence" in txt)
    page.screenshot(path=str(OUT / "confidence-99.png"))
    print("minimum restored:", set_minimum(page, 80))
    b.close()
