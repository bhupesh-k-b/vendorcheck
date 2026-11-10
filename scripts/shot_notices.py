"""Screenshot: bench with the documented happy path, and the typed-only / documents-only notices. Usage: shot_notices.py"""
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1000})
    page.on("pageerror", lambda e: print("JS ERROR", e))
    # bench
    page.goto(BASE + "/bench")
    page.click("#bench-run")
    page.wait_for_selector("#bench-summary")
    print(page.inner_text("#bench-summary")[:80])
    page.locator("tr:has-text('Happy path with all documents')").first.scroll_into_view_if_needed()
    page.screenshot(path=str(OUT / "bench-h2.png"))
    # typed only (Zoho sample has no files): notices
    page.goto(BASE + "/new")
    page.click("#sample-menu-btn")
    page.click('[data-example="zoho_duplicate"]')
    page.wait_for_timeout(400)
    page.click("#submit-btn")
    page.wait_for_url(re.compile(r".*/runs/\d+"))
    page.wait_for_selector("#run-done", state="attached", timeout=180000)
    page.wait_for_timeout(600)
    print("chip:", page.locator("text=No documents provided").count(), "| checklist notice:", page.locator("#no-documents").count())
    page.locator("#checklist").screenshot(path=str(OUT / "typed-only-checklist.png"))
    page.screenshot(path=str(OUT / "typed-only-top.png"))
    b.close()
