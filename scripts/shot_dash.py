"""Screenshot the dashboard."""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto("http://127.0.0.1:8765/")
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(OUT / "dash.png"))
    b.close()
