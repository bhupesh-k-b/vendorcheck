"""Load every sample on /new and report which key fields the form shows. Nothing is submitted."""
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1000})
    page.on("pageerror", lambda e: print("JS ERROR", e))
    page.goto(BASE + "/new")
    page.wait_for_load_state("networkidle")
    keys = page.eval_on_selector_all("[data-example]", "els => els.map(e => e.dataset.example)")
    print(f"{len(keys)} samples")
    for k in keys:
        page.click("#sample-menu-btn")
        page.click(f'[data-example="{k}"]')
        page.wait_for_timeout(250)
        f = page.evaluate("""() => { const d = Alpine.$data(document.querySelector('form[action="/submit"]')); return {...d.fields, msme: d.msme, samples: d.samples}; }""")
        ident = f.get("gstin") or f.get("tax_id") or f.get("iban")
        flag = "" if (f.get("legal_name") and ident and (f.get("bank_account") or f.get("iban"))) else "   <-- INCOMPLETE"
        print(f"{k:20} name={bool(f.get('legal_name'))!s:5} id={(ident or '-')[:18]:18} bank={bool(f.get('bank_account') or f.get('iban'))!s:5} udyam={f.get('udyam_number') or '-':20} msme={f['msme']:3} files={len([s for s in f['samples'].split(',') if s])}{flag}")
    b.close()
