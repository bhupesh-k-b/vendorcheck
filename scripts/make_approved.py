"""Create one approved happy-path case (Zoho, live GST) through the real UI flow. Needs the server on :8765 and GSTINAPI_KEY."""
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

import sys
KEY = sys.argv[1] if len(sys.argv) > 1 else "zoho"
BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)


def role(page, who):
    page.select_option("#role", who)
    page.wait_for_load_state("networkidle")


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
    page.on("pageerror", lambda e: print("JS ERROR", e))
    page.goto(BASE + "/new")
    page.wait_for_load_state("networkidle")
    page.click("#sample-menu-btn")
    page.click(f"[data-example=\"{KEY}\"]")
    page.wait_for_timeout(600)
    page.click("#submit-btn")
    page.wait_for_url(re.compile(r".*/runs/\d+"))
    page.wait_for_selector("#run-done", state="attached", timeout=180000)
    page.wait_for_timeout(500)
    print("after run:", page.inner_text("h2:has-text('Pending'), h2:has-text('Approved'), h2:has-text('Rejected')")[:160])
    role(page, "arjun")
    form = 'form[action$="/resolve"]'
    page.select_option(form + " select[name=outcome]", "confirmed")
    page.select_option(form + " select[name=method]", "Called the bank")
    page.fill(form + " input[name=note]", "Called the bank branch; account holder matches the vendor.")
    page.click(form + " button")
    page.wait_for_load_state("networkidle")
    role(page, "neha")
    page.click("button[name=decision][value=approve]")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)
    print("url:", page.url)
    print("final:", page.inner_text("h2:has-text('Pending'), h2:has-text('Approved'), h2:has-text('Rejected')")[:160])
    page.screenshot(path=str(OUT / f"approved-{KEY}.png"))
    role(page, "priya")
    b.close()
