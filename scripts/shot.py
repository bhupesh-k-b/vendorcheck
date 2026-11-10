"""Ad-hoc Playwright helper used while building: drive one flow and save screenshots to screenshots/.
Usage: shot.py <flow>   (flows: zoho, tcs, lookalike)"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)


def run(flow: str):
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1366, "height": 900})
        page.on("console", lambda m: print("console:", m.type, m.text) if m.type in ("error",) else None)
        page.goto(BASE + "/new")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT / f"{flow}-1-new.png"))
        key = {"zoho": "zoho", "tcs": "tcs", "lookalike": "zoho_lookalike"}[flow]
        page.click(f'[data-example="{key}"]')
        page.wait_for_timeout(700)
        page.screenshot(path=str(OUT / f"{flow}-2-filled.png"), full_page=True)
        page.click("#submit-btn")
        page.wait_for_url("**/runs/*")
        for i in range(3):
            page.wait_for_timeout(1100)
            page.screenshot(path=str(OUT / f"{flow}-3-running-{i}.png"))
        page.wait_for_selector("#run-done", state="attached", timeout=60000)
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / f"{flow}-4-done.png"), full_page=True)
        print("final url", page.url)
        b.close()


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "zoho")
