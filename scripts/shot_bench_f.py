"""Run the test bench and screenshot the FSSAI scenarios."""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "screenshots"
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1100})
    page.goto("http://127.0.0.1:8765/bench")
    page.click("#bench-run")
    page.wait_for_selector("#bench-summary")
    print(page.inner_text("#bench-summary")[:80])
    row = page.locator("tr:has-text('FSSAI licence required with other things')").first
    row.scroll_into_view_if_needed()
    page.screenshot(path=str(OUT / "bench-fssai.png"))
    b.close()
