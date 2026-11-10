"""Submit the user's real fssai.webp (already stored) with a typed company name, and show what is read from it and how it is checked."""
import re
from pathlib import Path

from playwright.sync_api import sync_playwright
from sqlmodel import Session, select

from vendorcheck.context import default_ctx
from vendorcheck.models import Version

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)
with Session(default_ctx().engine) as s:
    f = next(v.files[0] for v in s.exec(select(Version)).all() if v.files and v.files[0]["name"] == "fssai.webp")
path = f["path"]

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1000})
    page.on("pageerror", lambda e: print("JS ERROR", e))
    page.goto(BASE + "/new")
    page.wait_for_load_state("networkidle")
    page.set_input_files('input[name="files"]', path)
    page.fill("#f-legal_name", "Mehta and Sons Traders")
    page.fill('input[name="contact_name"]', "Rajesh Mehta")
    page.fill('input[name="contact_email"]', "accounts@example.com")
    page.click("#submit-btn")
    page.wait_for_url(re.compile(r".*/runs/\d+"))
    page.wait_for_selector("#run-done", state="attached", timeout=300000)
    page.wait_for_timeout(800)
    print("headline:", page.inner_text('h2:has-text("Pending"), h2:has-text("Approved")')[:100])
    if page.locator("#compliance").count():
        print("compliance card:", re.sub(r"\s+", " ", page.locator("#compliance").inner_text())[:420])
        page.locator("#compliance").screenshot(path=str(OUT / "real-fssai-card.png"))
    mx = page.locator("#mx-table")
    if mx.count():
        print("columns:", [t.strip() for t in mx.locator("thead th").all_inner_texts()])
        for tr in mx.locator("tbody tr").all():
            print("  row:", re.sub(r"\s+", " ", tr.locator("th").inner_text())[:45])
        page.locator("#consistency").screenshot(path=str(OUT / "real-fssai-consistency.png"))
        why = page.locator("#mx-why")
        if why.count():
            print("why flagged:", re.sub(r"\s+", " ", why.inner_text())[:360])
    b.close()
