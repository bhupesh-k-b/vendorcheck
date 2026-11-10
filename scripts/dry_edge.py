"""Dry-run an example and print the headline, next steps and email subject. Usage: dry_edge.py <example-key>"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto(BASE + "/new")
    page.wait_for_load_state("networkidle")
    page.click("#sample-menu-btn")
    page.click(f'[data-example="{sys.argv[1]}"]')
    page.wait_for_timeout(500)
    page.click("#submit-btn")
    page.wait_for_url(re.compile(r".*/runs/\d+"))
    page.wait_for_selector("#run-done", state="attached", timeout=180000)
    page.wait_for_timeout(600)
    print(page.url)
    print(page.inner_text("#run")[:1800])
    page.screenshot(path=str(OUT / f"edge-{sys.argv[1]}.png"))
    if page.locator("#consistency").count():
        page.locator("#consistency").screenshot(path=str(OUT / f"edge-{sys.argv[1]}-consistency.png"))
    b.close()
