"""Submit a sample document pack in the browser and screenshot the consistency table.
Usage: shot_pack.py kaveri_messy|kaveri_clean"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"


def main(key: str):
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1366, "height": 900})
        page.on("pageerror", lambda e: print("JS ERROR", e))
        page.goto(BASE + "/new")
        page.wait_for_load_state("networkidle")
        page.click(f'[data-example="{key}"]')
        page.wait_for_timeout(600)
        page.click("#submit-btn")
        page.wait_for_url(re.compile(r".*/runs/\d+"))
        page.wait_for_selector("#run-done", state="attached", timeout=240000)
        page.wait_for_timeout(1500)
        print(page.url)
        page.screenshot(path=str(OUT / f"{key}-full.png"), full_page=True)
        for sel, name in (("#consistency", "matrix"), ("#verify-links", "links")):
            if page.locator(sel).count():
                page.locator(sel).screenshot(path=str(OUT / f"{key}-{name}.png"))
        print(page.locator("#mx-score").inner_text() if page.locator("#mx-score").count() else "no matrix")
        if page.locator("#docs-panel").count():
            page.locator("#docs-panel").screenshot(path=str(OUT / f"{key}-docs.png"))
            page.locator('#docs-panel button:has-text("p.9")').first.click()
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT / f"{key}-viewer-p9.png"))
            page.keyboard.press("Escape")
        if page.locator("#email-panel").count():
            page.locator("#email-panel").screenshot(path=str(OUT / f"{key}-email.png"))
        b.close()


main(sys.argv[1])
