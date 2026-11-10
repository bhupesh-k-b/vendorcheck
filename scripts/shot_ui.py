"""Screenshot the main pages for a visual check. Usage: shot_ui.py <example-key>"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)


def main(key):
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda e: print("JS ERROR", e))
        page.goto(BASE + "/new")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT / "ui-new.png"), full_page=True)
        page.click("#sample-menu-btn")
        page.screenshot(path=str(OUT / "ui-new-menu.png"))
        page.click(f'[data-example="{key}"]')
        page.wait_for_timeout(900)
        page.screenshot(path=str(OUT / "ui-new-filled.png"), full_page=True)
        page.click("#submit-btn")
        page.wait_for_url(re.compile(r".*/runs/\d+"))
        page.wait_for_selector("#run-done", state="attached", timeout=180000)
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / "ui-run.png"), full_page=True)
        for name, path in [("dashboard", "/"), ("queue", "/queue"), ("vendors", "/vendors"), ("settings", "/settings"), ("bench", "/bench")]:
            page.goto(BASE + path)
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(OUT / f"ui-{name}.png"), full_page=True)
        b.close()


main(sys.argv[1])
