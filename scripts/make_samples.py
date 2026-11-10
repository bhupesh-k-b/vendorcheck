"""Generates samples/blank_vendor_form.pdf (our own one-page form, designed for handwriting) and a typed
copy filled with Infosys's PUBLIC details. No imitation of any government document is produced."""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent.parent / "samples"
W, H = A4
ACCENT = HexColor("#244fd6")
GREY = HexColor("#666666")

BOX_FIELDS = [("GSTIN", "gstin", 15), ("PAN", "pan", 10), ("CIN (companies only)", "cin", 21), ("Bank account number", "bank_account", 18), ("IFSC", "ifsc", 11)]
LINE_FIELDS = [("Legal business name (as on GST certificate)", "legal_name"), ("Trade name (if different)", "trade_name"), ("Account holder name", "account_holder"),
               ("Contact person", "contact_name"), ("Contact email", "contact_email"), ("Contact phone", "contact_phone")]


def draw(c: canvas.Canvas, values: dict | None = None):
    v = values or {}
    c.setFillColor(ACCENT)
    c.rect(0, H - 70, W, 70, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(40, H - 38, "Vendor Registration Form")
    c.setFont("Helvetica", 9.5)
    c.drawString(40, H - 56, "Please print clearly in CAPITAL LETTERS, one character per box. Do not attach Aadhaar or personal PAN cards.")
    c.setFillColorRGB(0, 0, 0)
    y = H - 110

    def label(text, yy):
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(GREY)
        c.drawString(40, yy + 20, text.upper())
        c.setFillColorRGB(0, 0, 0)

    for text, key in LINE_FIELDS[:3]:
        label(text, y)
        c.setStrokeColor(GREY)
        c.line(40, y, W - 40, y)
        if v.get(key):
            c.setFont("Courier-Bold", 13)
            c.drawString(46, y + 4, str(v[key]))
        y -= 46
    for text, key, n in BOX_FIELDS:
        label(text, y + 9)
        size = min(24, (W - 80) / n)
        c.setStrokeColor(GREY)
        for i in range(n):
            c.rect(40 + i * size, y - 4, size, size + 2, stroke=1, fill=0)
            ch = (str(v.get(key, "")) + " " * n)[i]
            if ch.strip():
                c.setFont("Courier-Bold", size * 0.7)
                c.drawCentredString(40 + i * size + size / 2, y + 2, ch)
        y -= 50
    for text, key in LINE_FIELDS[3:]:
        label(text, y)
        c.setStrokeColor(GREY)
        c.line(40, y, W - 40, y)
        if v.get(key):
            c.setFont("Courier-Bold", 13)
            c.drawString(46, y + 4, str(v[key]))
        y -= 46
    label("Do you claim MSME status?", y)
    c.setFont("Helvetica", 11)
    for i, opt in enumerate(["Yes", "No"]):
        x = 46 + i * 70
        c.rect(x, y - 2, 12, 12)
        if v.get("msme") == opt:
            c.setFont("Courier-Bold", 13)
            c.drawString(x + 1.5, y, "X")
            c.setFont("Helvetica", 11)
        c.drawString(x + 18, y, opt)
    c.drawString(200, y, "Udyam number:")
    c.line(285, y - 2, W - 40, y - 2)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(GREY)
    c.drawString(40, 40, "Declaration: the details above are true and I am authorised to give them on behalf of the business.     Signature: ____________________")


def build(path: Path, values: dict | None):
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Vendor Registration Form")
    draw(c, values)
    c.save()
    print("wrote", path)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    build(OUT / "blank_vendor_form.pdf", None)
    build(OUT / "infosys_vendor_form_typed.pdf", {
        "legal_name": "INFOSYS LIMITED", "trade_name": "INFOSYS LIMITED", "gstin": "29AAACI4798L1ZU", "pan": "AAACI4798L", "cin": "L85110KA1981PLC013115",
        "bank_account": "000890289871772", "ifsc": "SCBL0036078", "account_holder": "INFOSYS LIMITED", "contact_name": "ACCOUNTS DESK",
        "contact_email": "accounts@example.com", "contact_phone": "9999999999", "msme": "No"})
