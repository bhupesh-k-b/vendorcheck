"""Drive the international examples in the browser and save screenshots. Usage: shot_intl.py <example-key> [<example-key>...]"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"


def main(keys):
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1366, "height": 900})
        page.on("pageerror", lambda e: print("JS ERROR", e))
        for key in keys:
            page.goto(BASE + "/new")
            page.wait_for_load_state("networkidle")
            page.click(f'[data-example="{key}"]')
            page.wait_for_timeout(900)
            page.screenshot(path=str(OUT / f"intl-{key}-form.png"), full_page=True)
            page.click("#submit-btn")
            page.wait_for_url(re.compile(r".*/runs/\d+"))
            page.wait_for_selector("#run-done", state="attached", timeout=120000)
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT / f"intl-{key}-run.png"), full_page=True)
            banner = page.locator("#run").first.inner_text()[:240].replace("\n", " ")
            print(key, "->", page.url, "|", banner)
        b.close()


main(sys.argv[1:])
