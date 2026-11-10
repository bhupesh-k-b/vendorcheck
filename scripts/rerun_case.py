"""Re-run all checks on a case and screenshot the result. Usage: rerun_case.py <run-id>"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto(f"{BASE}/runs/{sys.argv[1]}")
    page.wait_for_load_state("networkidle")
    page.click("button:has-text('Re-run all checks')")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)
    page.wait_for_selector("#run-done", state="attached", timeout=180000)
    page.wait_for_timeout(800)
    print(page.url)
    print(page.inner_text("h2:has-text('Approved'), h2:has-text('Pending'), h2:has-text('Rejected')")[:200])
    page.screenshot(path=str(OUT / "approved2.png"))
    b.close()
