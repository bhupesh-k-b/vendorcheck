"""Open the page viewer and check nothing paints over it. Usage: shot_viewer.py <run-id>"""
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
    page.locator("#consistency").scroll_into_view_if_needed()
    page.locator("#docs-panel button:has(img)").first.click()
    page.wait_for_timeout(600)
    # what is the topmost element at points that previously showed the table column and the top bar?
    tops = page.evaluate("""() => {
        const modal = document.querySelector('#docs-panel [role=dialog]');
        const pts = [[420, 600], [420, 750], [600, 30], [1200, 30]];
        return pts.map(([x, y]) => { const el = document.elementFromPoint(x, y); return [x, y, !!(el && modal.contains(el)), el ? el.tagName : null]; });
    }""")
    for t in tops:
        print("point", t[0], t[1], "inside viewer:", t[2], t[3])
    page.screenshot(path=str(OUT / "viewer-fixed.png"))
    b.close()
