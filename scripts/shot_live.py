"""Capture the live run view mid-run, then the finished run and the dashboard. Usage: shot_live.py <example-key>"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.on("pageerror", lambda e: print("JS ERROR", e))
    page.goto(BASE + "/new")
    page.wait_for_load_state("networkidle")
    page.click("#sample-menu-btn")
    page.click(f'[data-example="{sys.argv[1]}"]')
    page.wait_for_timeout(600)
    page.click("#submit-btn")
    page.wait_for_url(re.compile(r".*/runs/\d+"))
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT / "live-mid.png"))
    page.wait_for_selector("#run-done", state="attached", timeout=180000)
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "live-done.png"), clip={"x": 0, "y": 0, "width": 1440, "height": 900})
    page.goto(BASE + "/")
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(OUT / "live-dashboard.png"))
    b.close()
