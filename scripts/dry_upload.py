"""Upload files from a demo_documents folder with the Kaveri typed details and print the checklist. Usage: dry_upload.py <folder> [<folder>...]"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "screenshots"
files = []
for folder in sys.argv[1:]:
    files += sorted(str(p) for p in (ROOT / folder).iterdir() if p.suffix in (".pdf", ".png", ".jpg"))

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto(BASE + "/new")
    page.wait_for_load_state("networkidle")
    page.click("#sample-menu-btn")
    page.click('[data-example="kaveri_complete"]')
    page.wait_for_timeout(500)
    page.evaluate("Alpine.$data(document.querySelector('form[action=\"/submit\"]')).samples = ''")
    page.set_input_files('input[name="files"]', files)
    page.wait_for_timeout(300)
    page.click("#submit-btn")
    page.wait_for_url(re.compile(r".*/runs/\d+"))
    page.wait_for_selector("#run-done", state="attached", timeout=240000)
    page.wait_for_timeout(800)
    print(page.url, "| files:", len(files))
    print(page.inner_text("h2:has-text('Pending'), h2:has-text('Approved'), h2:has-text('Rejected')")[:200])
    t = page.inner_text("#checklist") if page.locator("#checklist").count() else "(no checklist)"
    print(re.sub(r"\n+", " | ", t)[:900])
    page.screenshot(path=str(OUT / "upload-check.png"))
    b.close()
