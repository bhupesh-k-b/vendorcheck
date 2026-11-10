"""Builds realistic-looking SPECIMEN submission packs for a FICTIONAL company (Kaveri Precision Components).

    .venv/bin/python scripts/make_pack.py [path/to/blank_registration_form.pdf]

Outputs in samples/:
  kaveri_pack_clean.pdf   long PDF: the 11-page registration form (filled in) + PAN card + GST certificate + cancelled cheque + incorporation certificate, all consistent
  kaveri_pack_messy.pdf   the same, but with deliberate inconsistencies (see MESSY below)
  kaveri_pan_card.png     the PAN card alone, as a phone-style image

Safety: the company, numbers and people are fictional. Every page carries a diagonal SPECIMEN watermark, there are no
government emblems or logos, and the cheque has no real bank branding."""
import io
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vendorcheck import validators as v  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples"
DEFAULT_FORM = next(iter(sorted(Path.home().glob("Downloads/RMC1_*.pdf"))), None)

NAME = "KAVERI PRECISION COMPONENTS PRIVATE LIMITED"
PAN = "AAACK5521D"
GSTIN = v.with_gstin_check_char("27" + PAN + "1Z")
CIN = "U29253MH2014PTC152873"
ACCOUNT, IFSC = "50200045678912", "HDFC0000001"
ADDRESS = "Plot 41, MIDC Bhosari, Pune, Maharashtra"
TRUTH = dict(name=NAME, pan=PAN, gstin=GSTIN, cin=CIN, account=ACCOUNT, ifsc=IFSC, trade="KAVERI PRECISION COMPONENTS", doi="12 March 2014")
# deliberate inconsistencies in the messy pack
MESSY = dict(form_pan="AAACK5512D", cheque_account="50200045678921", cheque_ifsc="", pan_card_name="KAVERI PRECISION COMPONENT PRIVATE LIMITED",
             form_cin="")


def font(size: int, bold=False, mono=False):
    names = (["Courier New Bold.ttf", "Courier New.ttf"] if mono else ["Arial Bold.ttf", "Arial.ttf"] if bold else ["Arial.ttf"])
    for n in names:
        for d in ("/System/Library/Fonts/Supplemental/", "/Library/Fonts/"):
            if (Path(d) / n).exists():
                return ImageFont.truetype(str(Path(d) / n), size)
    return ImageFont.load_default()


def watermark(img: Image.Image) -> Image.Image:
    w, h = img.size
    layer = Image.new("RGBA", (w * 2, w * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    txt = "SPECIMEN · FICTIONAL COMPANY · DEMO ONLY"
    f = font(max(24, w // 22), bold=True)
    for i in range(-2, 5):
        d.text((w // 6, i * h // 3 + w // 2), txt, font=f, fill=(200, 30, 30, 70))
    layer = layer.rotate(28, resample=Image.BICUBIC).crop((w // 2, w // 2, w // 2 + w, w // 2 + h))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def pan_card(name: str, pan: str, doi: str = "") -> Image.Image:
    img = Image.new("RGB", (1011, 638), (214, 232, 247))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1011, 96], fill=(36, 79, 140))
    d.text((40, 24), "INCOME TAX DEPARTMENT", font=font(40, True), fill="white")
    d.text((640, 34), "GOVT. OF INDIA", font=font(30, True), fill="white")
    d.text((40, 120), "Permanent Account Number Card", font=font(26), fill=(30, 40, 60))
    d.text((40, 190), pan, font=font(70, True, mono=True), fill=(15, 20, 30))
    d.text((40, 300), "Name", font=font(22), fill=(80, 90, 110))
    d.text((40, 328), name, font=font(34, True), fill=(15, 20, 30))
    d.text((40, 420), "Date of Incorporation / Formation", font=font(22), fill=(80, 90, 110))
    d.text((40, 448), doi or TRUTH["doi"], font=font(32, True), fill=(15, 20, 30))
    d.rectangle([740, 440, 960, 590], outline=(90, 100, 120), width=2)
    d.text((770, 505), "Signature", font=font(22), fill=(120, 130, 150))
    return watermark(img)


def gst_certificate(name: str, gstin: str, trade: str, address: str = "", constitution: str = "Private Limited Company") -> Image.Image:
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    d.text((620, 90), "Government of India", font=font(34, True), fill="black", anchor="mm")
    d.text((620, 150), "Form GST REG-06", font=font(30), fill="black", anchor="mm")
    d.text((620, 215), "REGISTRATION CERTIFICATE", font=font(42, True), fill="black", anchor="mm")
    d.text((620, 265), "[See rule 10(1)]", font=font(24), fill=(80, 80, 80), anchor="mm")
    rows = [("Registration Number", gstin), ("1. Legal Name", name), ("2. Trade Name, if any", trade), ("3. Constitution of Business", constitution),
            ("4. Address of Principal Place of Business", address or (ADDRESS + " - 411026")), ("5. Date of Liability", "01/07/2017"),
            ("6. Date of Validity", "From 01/07/2017   To   Not Applicable"), ("7. Type of Registration", "Regular")]
    y = 360
    for k, val in rows:
        d.rectangle([90, y, 1150, y + 110], outline=(120, 120, 120), width=2)
        d.text((110, y + 14), k, font=font(26, True), fill="black")
        d.text((110, y + 58), val, font=font(30, mono=(k == "Registration Number")), fill="black")
        y += 130
    d.text((90, y + 40), "This is a computer generated specimen. No signature is required.", font=font(24), fill=(90, 90, 90))
    return watermark(img)


def cheque(account: str, ifsc: str, name: str) -> Image.Image:
    img = Image.new("RGB", (1700, 760), (250, 246, 232))
    d = ImageDraw.Draw(img)
    d.text((60, 40), "SPECIMEN CANCELLED CHEQUE", font=font(40, True), fill=(40, 60, 90))
    d.text((60, 100), ADDRESS.split(",")[1].strip() + " Branch", font=font(28), fill=(60, 60, 60))
    d.text((1180, 40), "Date  __ __ / __ __ / __ __ __ __", font=font(28), fill=(60, 60, 60))
    d.text((60, 200), "Pay", font=font(30), fill="black")
    d.line([140, 235, 1600, 235], fill="black", width=2)
    d.text((60, 280), "Rupees", font=font(30), fill="black")
    d.line([190, 315, 1300, 315], fill="black", width=2)
    d.rectangle([1320, 270, 1640, 340], outline="black", width=3)
    d.text((70, 380), "A/c No.", font=font(30), fill="black")
    d.text((240, 376), account, font=font(40, True, mono=True), fill=(20, 20, 60))
    d.text((70, 440), "IFSC", font=font(30), fill="black")
    d.text((240, 436), ifsc or "", font=font(40, True, mono=True), fill=(20, 20, 60))
    d.text((700, 470), "For  " + name, font=font(26, True), fill=(20, 20, 60))
    d.line([960, 600, 1620, 600], fill="black", width=2)
    d.text((1180, 615), "Authorised Signatory", font=font(24), fill=(80, 80, 80))
    d.text((60, 690), "⑈000123⑈  400240003⑆  " + (account[-6:] or "") + "⑈  31", font=font(36, mono=True), fill=(30, 30, 30))
    d.line([0, 0, 1700, 760], fill=(60, 60, 60), width=6)          # cancelled: struck through
    d.line([0, 760, 1700, 0], fill=(60, 60, 60), width=6)
    d.text((620, 330), "CANCELLED", font=font(90, True), fill=(180, 40, 40))
    return watermark(img)


def incorporation(name: str, cin: str) -> Image.Image:
    img = Image.new("RGB", (1240, 1754), (252, 252, 247))
    d = ImageDraw.Draw(img)
    d.text((620, 120), "Certificate of Incorporation", font=font(46, True), fill="black", anchor="mm")
    d.text((620, 190), "[Pursuant to sub-section (2) of section 7 of the Companies Act, 2013]", font=font(24), fill=(70, 70, 70), anchor="mm")
    lines = ["I hereby certify that", "", name, "", "is this day incorporated under the Companies Act, 2013 (18 of 2013)",
             "and that the company is a company limited by shares.", "", "The Corporate Identity Number of the company is", cin, "",
             "The Permanent Account Number of the company is " + PAN, "", f"Given at Mumbai this {TRUTH['doi'].split()[0]}th day of March Two thousand fourteen.",
             "", "", "Registrar of Companies, Maharashtra", "Registered Office: " + ADDRESS]
    y = 330
    for ln in lines:
        big = ln in (name, cin)
        d.text((620, y), ln, font=font(34 if big else 28, big, mono=(ln == cin)), fill="black", anchor="mm")
        y += 62
    return watermark(img)


def fill_form(src: Path, pan: str, cin: str) -> pymupdf.Document:
    """Write the vendor's answers onto the blank registration form: some sections filled, some left empty."""
    doc = pymupdf.open(src)
    ink = (0.05, 0.1, 0.55)

    def put(pg: int, label: str, text: str, nth=0, dx=6, dy=0):
        rects = doc[pg].search_for(label)
        if len(rects) > nth:
            r = rects[nth]
            doc[pg].insert_text((r.x1 + dx, r.y1 - 2 + dy), text, fontsize=9.5, fontname="cour", color=ink)
        else:
            print("  (label not found:", label, ")")

    put(0, "Name of the Company/ Vendor :", NAME)
    put(0, "REGD.Office:", ADDRESS)
    put(0, "PINCode:", "411026", 0)
    put(0, "Email:", "ap@kaveri.example", 0)
    put(0, "Mobile:", "9822000123", 0)
    put(0, "Date of incorporation of the company/ commencement of production :", TRUTH["doi"])
    put(0, "NatureofCompany:", "Private Limited Company")
    put(0, "Name:", "Ravi Kulkarni (Managing Director)", 0)
    put(0, "Category of Industry :", "Precision machined components")
    put(1, "PrincipalBanker:", "Specimen Bank, Bhosari Branch")
    put(1, "AccountNo.:", ACCOUNT)
    put(1, "IFSCCode:", IFSC)
    put(1, "TANNo.:", "PNEK12345E")
    put(1, "Valid excise registration Number :", "Not applicable (GST regime)")
    # items the form has no dedicated field for: the vendor writes the registration numbers beside the closest item
    put(4, "Valid State / Vat / Central Sales Tax Registration Certificate :", "GSTIN " + GSTIN)
    put(6, "Income Tax Returns for Three Years (of the firm) :", "PAN " + pan)
    if cin:
        put(4, "Details of Registration with :", "CIN " + cin)
    return doc


def append_image(doc: pymupdf.Document, img: Image.Image):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=88)
    w, h = img.size
    page = doc.new_page(width=595, height=842 if h >= w else 595 * h / w)
    page.insert_image(page.rect, stream=buf.getvalue())


def build(path: Path, form_src: Path, messy: bool):
    m = MESSY if messy else {}
    doc = fill_form(form_src, m.get("form_pan", PAN), m.get("form_cin", CIN) if messy else CIN)
    append_image(doc, pan_card(m.get("pan_card_name", NAME), PAN))
    append_image(doc, gst_certificate(NAME, GSTIN, TRUTH["trade"]))
    append_image(doc, cheque(m.get("cheque_account", ACCOUNT), m.get("cheque_ifsc", IFSC) if messy else IFSC, NAME))
    append_image(doc, incorporation(NAME, CIN))
    doc.save(str(path))
    print("wrote", path, f"({len(doc)} pages)")


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FORM
    if not src or not src.exists():
        sys.exit("Pass the blank registration form PDF as the first argument.")
    OUT.mkdir(exist_ok=True)
    (OUT / "registration_form_blank.pdf").write_bytes(src.read_bytes())
    build(OUT / "kaveri_pack_clean.pdf", src, messy=False)
    build(OUT / "kaveri_pack_messy.pdf", src, messy=True)
    pan_card(NAME, PAN).save(OUT / "kaveri_pan_card.png")
    print("fictional identifiers:", dict(pan=PAN, gstin=GSTIN, cin=CIN, account=ACCOUNT))
