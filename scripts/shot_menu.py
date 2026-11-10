"""Check the sample menu order and that loading a sample shows no explanation banner."""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "screenshots"
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto("http://127.0.0.1:8765/new")
    page.wait_for_load_state("networkidle")
    page.click("#sample-menu-btn")
    items = page.eval_on_selector_all("[data-example]", "els => els.map(e => e.textContent.trim())")
    print("first 3 menu items:", items[:3], "| total", len(items))
    page.screenshot(path=str(OUT / "menu.png"))
    page.click('[data-example="happy_documents"]')
    page.wait_for_timeout(400)
    banner = page.locator('[role=status]:visible').count()
    print("banner visible after loading:", banner)
    page.click("#sample-menu-btn")
    page.click('[data-example="zoho"]')
    page.wait_for_timeout(400)
    print("banner visible after loading zoho:", page.locator('[role=status]:visible').count())
    print("submit label for zoho:", page.inner_text("#submit-btn"))
    page.click("#sample-menu-btn")
    page.click('[data-example="happy_documents"]')
    page.wait_for_timeout(300)
    print("submit label for kaveri happy:", page.inner_text("#submit-btn"))
    page.screenshot(path=str(OUT / "kaveri-loaded.png"))
    b.close()
