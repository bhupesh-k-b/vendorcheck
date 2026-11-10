"""Builds the sample submissions (company-wise and random documents) into samples/.

    .venv/bin/python scripts/make_packs.py [path/to/RMC1_blank_form.pdf]

 1  rmc1_infosys_form_filled.pdf   your 11-page RMC1 form filled with Infosys's ORIGINAL public details (form only: incomplete on purpose)
 2  kaveri_complete_pack.pdf       ONE PDF holding every required document (fictional company, MSME)
 3  mehta_*.pdf                    a fictional proprietorship sending SEPARATE files; its electricity bill shows another address
 4  orchid_wrong_documents.pdf     a fictional company that attached the WRONG documents (brochure, invoice, someone else's PAN card)
 5  lakeview_us_pack.pdf           a fictional US company: W-9, bank confirmation letter, articles of organization
 6  rheinland_eu_pack.pdf          a fictional German company: VAT certificate, IBAN bank letter, commercial-register extract

Only the registration form in (1) carries a real company's public details, on the vendor's own form. Everything else is
fictional and every generated page carries a SPECIMEN watermark and no government emblem."""
import io
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import make_pack as mp  # noqa: E402
from vendorcheck import validators as v  # noqa: E402

OUT = mp.OUT
font, watermark = mp.font, mp.watermark


def text_doc(title: str, subtitle: str, rows: list[tuple[str, str]], footer: str = "", size=(1240, 1754)) -> Image.Image:
    """A plain printed-looking document: title block, then label/value rows."""
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    d.text((size[0] // 2, 110), title, font=font(44, True), fill="black", anchor="mm")
    if subtitle:
        d.text((size[0] // 2, 175), subtitle, font=font(26), fill=(70, 70, 70), anchor="mm")
    y = 280
    for label, value in rows:
        if not label:                                   # free text line
            d.text((90, y), value, font=font(28), fill="black")
            y += 62
            continue
        d.text((90, y), label, font=font(26, True), fill=(60, 60, 60))
        y += 40
        for line in str(value).split("\n"):
            d.text((90, y), line, font=font(30), fill="black")
            y += 42
        y += 26
    if footer:
        d.text((90, size[1] - 120), footer, font=font(24), fill=(90, 90, 90))
    return watermark(img)


def to_pdf(images: list[Image.Image], path: Path, form: pymupdf.Document | None = None):
    doc = form or pymupdf.open()
    for im in images:
        mp.append_image(doc, im)
    doc.save(str(path))
    print("wrote", path.name, f"({len(doc)} page{'s' if len(doc) != 1 else ''})")


def gstin_for(state: str, pan: str) -> str:
    return v.with_gstin_check_char(state + pan + "1Z")


def electricity_bill(name: str, address_lines: list[str], consumer="2210045871") -> Image.Image:
    return text_doc("ELECTRICITY BILL", "State Distribution Company (specimen)",
                    [("Consumer No", consumer), ("Consumer Name", name), ("Service Address", "\n".join(address_lines)),
                     ("Billing Period", "01 Sep 2025 to 30 Sep 2025"), ("Units Consumed", "4,860 kWh"), ("Amount Due", "Rs. 52,430.00")],
                    "Specimen utility bill for demonstration. Not a real bill.")


def udyam_certificate(name: str, number: str, kind="Micro", activity="Manufacturing") -> Image.Image:
    return text_doc("UDYAM REGISTRATION CERTIFICATE", "Ministry of Micro, Small and Medium Enterprises (specimen)",
                    [("Udyam Registration Number", number), ("Name of Enterprise", name), ("Type of Enterprise", kind), ("Major Activity", activity),
                     ("Date of Incorporation", "12 March 2014")], "Specimen for demonstration. Not a real Udyam certificate.")


def fill_rmc1(src: Path, v_: dict) -> pymupdf.Document:
    """Write a vendor's answers onto the RMC1 form. Sections without a value are left empty (an incomplete form)."""
    doc = pymupdf.open(src)
    ink = (0.05, 0.1, 0.55)

    def put(pg, label, text, nth=0):
        if not text:
            return
        rects = doc[pg].search_for(label)
        if len(rects) > nth:
            r = rects[nth]
            doc[pg].insert_text((r.x1 + 6, r.y1 - 2), text, fontsize=9, fontname="cour", color=ink)
        else:
            print("  (label not found:", label, ")")
    put(0, "Name of the Company/ Vendor :", v_.get("name"))
    put(0, "REGD.Office:", v_.get("address"))
    put(0, "PINCode:", v_.get("pin"))
    put(0, "Email:", v_.get("email"))
    put(0, "Mobile:", v_.get("mobile"))
    put(0, "Date of incorporation of the company/ commencement of production :", v_.get("doi"))
    put(0, "NatureofCompany:", v_.get("nature"))
    put(0, "Category of Industry :", v_.get("industry"))
    put(1, "PrincipalBanker:", v_.get("banker"))
    put(1, "AccountNo.:", v_.get("account"))
    put(1, "IFSCCode:", v_.get("ifsc"))
    put(1, "TANNo.:", v_.get("tan"))
    put(4, "Valid State / Vat / Central Sales Tax Registration Certificate :", ("GSTIN " + v_["gstin"]) if v_.get("gstin") else "")
    put(6, "Income Tax Returns for Three Years (of the firm) :", ("PAN " + v_["pan"]) if v_.get("pan") else "")
    put(4, "Details of Registration with :", ("CIN " + v_["cin"]) if v_.get("cin") else "")
    return doc


def build_munitions(rmc1: Path):
    """The RMC1 form filled with Munitions India Limited's public details. Its bank pages (9 and 10) are already in Munitions' own name,
    so here the bank account name MATCHES the vendor. Only this form: no imitation government documents."""
    to_pdf([], OUT / "rmc1_munitions_form_filled.pdf", fill_rmc1(rmc1, {
        "name": "MUNITIONS INDIA LIMITED", "address": "Ordnance Factory Khamaria, Jabalpur, Madhya Pradesh", "nature": "Public Limited Company",
        "industry": "Defence manufacturing (ammunition)", "banker": "State Bank of India, Ranjhi Branch (Code 03228)",
        "account": "40436892598", "ifsc": "SBIN0003228", "gstin": "23AAOCM8781H2ZX", "pan": "AAOCM8781H"}))


def build_all(rmc1: Path):
    OUT.mkdir(exist_ok=True)
    build_munitions(rmc1)

    # 1. RMC1 filled with Infosys's original public details; the vendor left phone, TAN and all attachments out.
    to_pdf([], OUT / "rmc1_infosys_form_filled.pdf", fill_rmc1(rmc1, {
        "name": "INFOSYS LIMITED", "address": "Plot No. 44, Electronics City, Hosur Road, Bengaluru, Karnataka", "pin": "560100", "email": "accounts@example.com",
        "doi": "2 July 1981", "nature": "Public Limited Company", "industry": "IT services and consulting", "banker": "Test account (Cashfree published test data)",
        "account": "000890289871772", "ifsc": "SCBL0036078", "gstin": "29AAACI4798L1ZU", "pan": "AAACI4798L", "cin": "L85110KA1981PLC013115"}))

    # 2. ONE PDF with every required document (fictional MSME company)
    n, pan, gst, cin = mp.NAME, mp.PAN, mp.GSTIN, mp.CIN
    addr = "Plot 41, MIDC Bhosari, Pune, Maharashtra - 411026"
    form = mp.fill_form(rmc1, pan, cin)
    to_pdf([mp.pan_card(n, pan), mp.gst_certificate(n, gst, mp.TRUTH["trade"], addr), mp.cheque(mp.ACCOUNT, mp.IFSC, n), mp.incorporation(n, cin),
            electricity_bill(n, ["Plot 41, MIDC Bhosari", "Pune, Maharashtra", "PIN 411026"]),
            udyam_certificate(n, "UDYAM-MH-26-0012345")], OUT / "kaveri_complete_pack.pdf", form)

    # 3. a proprietorship sending separate files; the bill is for a different address than the GST registration
    mn, mpan = "MEHTA AND SONS TRADERS", "AAAPM4521K"
    mgst = gstin_for("24", mpan)
    to_pdf([mp.pan_card("RAJESH MEHTA", mpan, "14 June 1979")], OUT / "mehta_pan_card.pdf")
    to_pdf([mp.gst_certificate(mn, mgst, "MEHTA TRADERS", "Shop 12, Relief Road, Ahmedabad, Gujarat - 380001", "Proprietorship")], OUT / "mehta_gst_certificate.pdf")
    to_pdf([mp.cheque("30110045671234", "HDFC0000001", mn)], OUT / "mehta_cancelled_cheque.pdf")
    to_pdf([udyam_certificate(mn, "UDYAM-GJ-01-0045678", "Small", "Trading")], OUT / "mehta_udyam_certificate.pdf")
    to_pdf([electricity_bill(mn, ["Plot 7, GIDC Vatva", "Ahmedabad, Gujarat", "PIN 382445"], "7710023456")], OUT / "mehta_electricity_bill.pdf")
    print("  Mehta:", mgst, mpan)

    # 4. the WRONG documents: a brochure, an unrelated invoice, someone else's PAN card, a bill; no GST certificate, cheque or incorporation
    on, opan = "ORCHID GARMENTS PRIVATE LIMITED", "AAACO7788P"
    wrong = [text_doc("ORCHID GARMENTS", "Company brochure", [("", "Premium cotton and linen garments."), ("", "Export quality since 2009."), ("", "Visit our showroom in Tiruppur."),
                                                              ("", "Our fabrics are woven in-house with certified yarn."), ("", "Ask for our spring catalogue.")]),
             text_doc("TAX INVOICE", "Invoice for goods supplied", [("Invoice No", "INV-2291"), ("Billed to", "Some Other Customer Pvt Ltd"), ("Item", "Cotton fabric 400 m"),
                                                                    ("Amount", "Rs. 1,84,000")], "Not a registration document."),
             mp.pan_card("SUNRISE EXPORTS PRIVATE LIMITED", "AAACS3321B", "3 May 2008"),
             electricity_bill(on, ["12 Mill Road", "Tiruppur, Tamil Nadu", "PIN 641604"])]
    to_pdf(wrong, OUT / "orchid_wrong_documents.pdf")
    print("  Orchid:", gstin_for("33", opan), opan)

    # 5. US company
    un = "LAKEVIEW INDUSTRIAL SUPPLY LLC"
    us = [text_doc("Form W-9", "Request for Taxpayer Identification Number and Certification (specimen)",
                   [("Name (as shown on your income tax return)", un), ("Business name", un), ("Federal tax classification", "Limited liability company"),
                    ("Address", "100 N Lake Street\nChicago, IL 60601\nUnited States"), ("Employer identification number", "12-3456789")],
                  "Specimen for demonstration. Not an IRS form."),
          text_doc("BANK CONFIRMATION LETTER", "Specimen Bank N.A.",
                   [("", "To whom it may concern,"), ("Account holder", un), ("Account number", "123456789012"), ("ABA routing number", "021000021"),
                    ("SWIFT/BIC", "SPBKUS33"), ("", "We confirm the account above is open and in good standing.")], "Specimen letter. No real bank."),
          text_doc("ARTICLES OF ORGANIZATION", "State of Illinois, Limited Liability Company (specimen)",
                   [("Name of LLC", un), ("Registered office", "100 N Lake Street, Chicago, IL 60601, United States"), ("Date of formation", "9 January 2016")],
                   "Specimen for demonstration.")]
    to_pdf(us, OUT / "lakeview_us_pack.pdf")

    # 6. German company
    rn = "RHEINLAND WERKZEUG GMBH"
    eu = [text_doc("VAT REGISTRATION CERTIFICATE", "Umsatzsteuer-Identifikationsnummer (specimen)",
                   [("VAT No", "DE123456789"), ("Registered name", rn), ("Address", "Industriestrasse 12\n40210 Duesseldorf\nGermany")], "Specimen for demonstration."),
          text_doc("BANK CONFIRMATION LETTER", "Specimen Bank AG",
                   [("", "To whom it may concern,"), ("Account holder", rn), ("IBAN", "DE89 3704 0044 0532 0130 00"), ("SWIFT/BIC", "COBADEFFXXX"),
                    ("", "We confirm the account above is held by the company named.")], "Specimen letter. No real bank."),
          text_doc("HANDELSREGISTER", "Commercial register extract (specimen)",
                   [("Firma", rn), ("Sitz", "Duesseldorf, Germany"), ("Rechtsform", "Gesellschaft mit beschraenkter Haftung (GmbH)")], "Specimen for demonstration.")]
    to_pdf(eu, OUT / "rheinland_eu_pack.pdf")


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else mp.DEFAULT_FORM
    if not src or not Path(src).exists():
        sys.exit("Pass the blank RMC1 registration form PDF as the first argument.")
    build_all(Path(src))
