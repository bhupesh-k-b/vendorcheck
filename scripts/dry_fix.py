"""Submit the vendor-portal correction for the case behind run <id> and print the resulting run. Usage: dry_fix.py <run-id>"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(f"{BASE}/runs/{sys.argv[1]}")
    page.wait_for_load_state("networkidle")
    link = page.get_attribute('a[href^="/v/"]', "href")
    case_href = page.get_attribute('a:has-text("Open submission")', "href")
    vp = ctx.new_page()
    vp.goto(BASE + link)
    for pair in sys.argv[2:]:
        k, v = pair.split("=")
        vp.fill(f'input[name="{k}"]', v)
    vp.click("button:has-text('Submit')")
    vp.wait_for_load_state("networkidle")
    vp.close()
    page.goto(BASE + case_href)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)
    page.wait_for_selector("#run-done", state="attached", timeout=180000)
    page.wait_for_timeout(600)
    print(page.inner_text("#run")[:1500])
    page.screenshot(path=str(OUT / "edge-v2.png"))
    b.close()
