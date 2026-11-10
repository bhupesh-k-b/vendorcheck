"""Screenshot one case page. Usage: shot_case.py <case-id> [tab]"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)
cid = sys.argv[1]
tab = sys.argv[2] if len(sys.argv) > 2 else "latest"
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto(f"http://127.0.0.1:8765/cases/{cid}?tab={tab}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / f"case-{cid}-{tab}.png"), full_page=(tab != "latest"), clip=None if tab != "latest" else {"x": 0, "y": 0, "width": 1440, "height": 1300})
    b.close()
