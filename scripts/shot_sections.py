"""Re-run a case and screenshot its result sections. Usage: shot_sections.py <case-id> <name>"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)
cid, name = sys.argv[1], sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1000})
    page.on("pageerror", lambda e: print("JS ERROR", e))
    page.goto(f"{BASE}/cases/{cid}")
    page.wait_for_load_state("networkidle")
    page.click("button:has-text('Re-run all checks')")
    page.wait_for_load_state("networkidle")
    page.goto(f"{BASE}/cases/{cid}")
    page.wait_for_selector("#run-done", state="attached", timeout=240000)
    page.wait_for_timeout(800)
    page.evaluate("document.querySelectorAll('details').forEach(d => { if (d.querySelector('#ev-h')) d.open = true })")
    for sel, tag in [("#checklist", "checklist"), ("#consistency", "consistency"), ("#verify-links", "links")]:
        if page.locator(sel).count():
            page.locator(sel).scroll_into_view_if_needed()
            page.locator(sel).screenshot(path=str(OUT / f"{name}-{tag}.png"))
    ev = page.locator("details:has(#ev-h)")
    if ev.count():
        ev.screenshot(path=str(OUT / f"{name}-evidence.png"))
    print("done", page.url)
    b.close()
