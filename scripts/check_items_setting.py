"""End to end for extra compliance items: switches visible, add FSSAI, switch incorporation off, run Mehta without and with the licence, restore."""
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)


def run_sample(page, key):
    page.goto(BASE + "/new")
    page.wait_for_load_state("networkidle")
    page.click("#sample-menu-btn")
    page.click(f'[data-example="{key}"]')
    page.wait_for_timeout(500)
    page.click("#submit-btn")
    page.wait_for_url(re.compile(r".*/runs/\d+"))
    page.wait_for_selector("#run-done", state="attached", timeout=300000)
    page.wait_for_timeout(800)


def show(page, label):
    head = page.inner_text('h2:has-text("Pending"), h2:has-text("Approved")')[:90]
    print(f"\n-- {label}: {head}")
    for li in page.locator("#checklist ul > li").all():
        print("   checklist:", re.sub(r"\s+", " ", li.inner_text())[:95])
    if page.locator("#compliance").count():
        for li in page.locator("#compliance ul > li").all():
            print("   summary:  ", re.sub(r"\s+", " ", li.inner_text())[:95])
    mx = page.locator("#mx-table")
    if mx.count():
        print("   consistency columns:", [t.strip() for t in mx.locator("thead th").all_inner_texts()])
        print("   consistency rows:", [re.sub(r"\s+", " ", t)[:40] for t in mx.locator("tbody th").all_inner_texts()])


with sync_playwright() as p:
    b = p.chromium.launch()
    # 1. switches must show even when the stylesheet never loads (a stale or blocked app.css)
    ctx = b.new_context(viewport={"width": 1440, "height": 1000})
    ctx.route("**/static/app.css*", lambda r: r.abort())
    page = ctx.new_page()
    page.goto(BASE + "/settings")
    page.wait_for_load_state("networkidle")
    sw = page.locator('label:has-text("Certificate of incorporation") input + span').first.bounding_box()
    print("switch visible without app.css:", bool(sw) and sw["width"] > 30 and sw["height"] > 15, sw and (round(sw["width"]), round(sw["height"])))
    page.locator('label:has-text("Certificate of incorporation")').screenshot(path=str(OUT / "switch-no-css.png"))
    ctx.close()

    page = b.new_page(viewport={"width": 1440, "height": 1000})
    page.on("pageerror", lambda e: print("JS ERROR", e))
    page.goto(BASE + "/settings")
    page.wait_for_load_state("networkidle")
    print("switches on page:", page.locator('input.peer[type=checkbox]').count())
    page.select_option('select[aria-label="Start from a template"]', "fssai")
    page.click("#add-item")
    page.locator('label:has-text("Certificate of incorporation") input + span').first.click()      # switch it off
    page.locator("#extra-items").screenshot(path=str(OUT / "items-settings.png"))
    page.click("#policy-save")
    page.wait_for_load_state("networkidle")
    print("saved:", page.inner_text("[role=status]")[:70], "| items:", page.locator('input[name="item_label"]').count(),
          "| incorporation on:", page.is_checked('input[name="doc__incorporation"]'))

    run_sample(page, "mehta_separate")
    show(page, "Mehta WITHOUT the licence")
    page.locator("#compliance").screenshot(path=str(OUT / "items-summary-missing.png"))
    page.locator("#consistency").screenshot(path=str(OUT / "items-consistency-missing.png"))
    page.goto(BASE + "/")
    page.wait_for_load_state("networkidle")
    print("dashboard row tag:", re.sub(r"\s+", " ", page.locator("tbody tr").first.inner_text())[:140])
    page.screenshot(path=str(OUT / "items-dashboard.png"))

    run_sample(page, "mehta_fssai")
    show(page, "Mehta WITH the licence page and number")
    page.locator("#compliance").screenshot(path=str(OUT / "items-summary-found.png"))
    page.locator("#consistency").screenshot(path=str(OUT / "items-consistency-found.png"))
    page.evaluate("document.querySelectorAll('details').forEach(d => { if (d.querySelector('#ev-h')) d.open = true })")
    ev = re.sub(r"[ \t]+", " ", page.locator("details:has(#ev-h)").inner_text())
    print("evidence FSSAI row:", [l for l in ev.splitlines() if "FSSAI" in l])

    # restore
    page.goto(BASE + "/settings")
    page.wait_for_load_state("networkidle")
    page.click('button[aria-label="Remove this item"]')
    page.locator('label:has-text("Certificate of incorporation") input + span').first.click()
    page.click("#policy-save")
    page.wait_for_load_state("networkidle")
    print("\nrestored: items", page.locator('input[name="item_label"]').count(), "| incorporation on:", page.is_checked('input[name="doc__incorporation"]'))
    b.close()
