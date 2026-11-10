"""Which documents does this vendor need to supply, and which were actually found? Pure functions.

Documents are identified per PAGE (see the Read stage), so it makes no difference whether the vendor sent one combined PDF,
several files, or photos: a PAN card on page 12 of a long PDF counts exactly like pan_card.pdf. Documents that belong to
another party (a bank form in someone else's name) never count."""
import re
from dataclasses import dataclass, field

from . import countries as cn
from . import validators as v

DOCS = {
    "pan_card": ("PAN card", ["pan_card"], ("Income Tax: Verify Your PAN", "https://eportal.incometax.gov.in/iec/foservices/#/pre-login/verifyYourPAN")),
    "gst_certificate": ("GST registration certificate", ["gst_certificate"], ("GST portal: Search Taxpayer", "https://services.gst.gov.in/services/searchtp")),
    "bank_document": ("Cancelled cheque or bank confirmation letter (in the vendor's own name)", ["cancelled_cheque_or_bank_letter", "bank_details_form"], None),
    "address_proof": ("Address proof (matching the registered address)", ["address_proof"], None),
    "udyam_certificate": ("Udyam registration certificate (MSME)", ["udyam_certificate"], ("Udyam: Verify", "https://udyamregistration.gov.in/Udyam_Verify.aspx")),
    "incorporation": ("Certificate of incorporation / business registration", ["incorporation_or_name_change_certificate"],
                      ("MCA: master data", "https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html")),
    "tax_form": ("Tax registration document (W-9 / W-8BEN, VAT or tax certificate)", ["tax_form_or_vat_certificate"], None),
}
COMPANY_SUFFIX = re.compile(r"\b(LIMITED|LTD|PRIVATE LIMITED|PVT LTD|LLP|LLC|INC|INCORPORATED|CORPORATION|CORP|GMBH|AG|SA|SAS|BV|NV|SRL|SPA|PTY|PLC|OY|AB|AS|APS)\b", re.I)


@dataclass
class Row:
    key: str
    label: str
    required: bool
    why: str                                   # why it is (not) required
    state: str                                 # found | missing | other_party | not_required
    where: str = ""                            # "kaveri.pdf p.12"
    link: tuple | None = None                  # (label, url)
    pages: list = field(default_factory=list)


def is_company_like(profile: dict) -> bool:
    name = v.normalise_name(profile.get("legal_name") or "")
    pan4 = (profile.get("pan") or "")[3:4].upper()
    return bool(profile.get("cin")) or pan4 == "C" or bool(COMPANY_SUFFIX.search(name)) or (pan4 == "F" and "LLP" in name)


def found_pages(doc_map: list[dict]) -> dict[str, list[dict]]:
    """doc_type -> [{file, page, foreign}] for every page where that document type was identified."""
    out: dict[str, list[dict]] = {}
    for f in doc_map:
        for pg in f["pages"]:
            for t in pg["types"]:
                out.setdefault(t["doc_type"], []).append({"file": f["name"], "page": pg["page"], "foreign": pg.get("foreign", "")})
    return out


def build(profile: dict, doc_map: list[dict]) -> list[Row]:
    country = (profile.get("country") or "").upper()
    india = country == "IN"
    pages = found_pages(doc_map)
    ifsc = profile.get("ifsc") or ""
    spec: list[tuple[str, bool, str]] = []
    if india:
        spec = [("pan_card", True, "every Indian vendor"),
                ("gst_certificate", bool(profile.get("gstin")), "a GSTIN was given" if profile.get("gstin") else "no GSTIN was given"),
                ("bank_document", True, "bank details must be backed by a document in the vendor's name"),
                ("address_proof", bool(profile.get("gstin")), "to match the GST registration address" if profile.get("gstin") else "no GST registration to match"),
                ("udyam_certificate", bool(profile.get("msme")), "MSME status was claimed" if profile.get("msme") else "MSME was not claimed"),
                ("incorporation", is_company_like(profile), "a company or LLP" if is_company_like(profile) else "not a company or LLP")]
    elif country:
        spec = [("tax_form", True, f"every vendor outside India ({cn.name_of(country)})"),
                ("bank_document", True, "bank details must be backed by a bank letter in the vendor's name"),
                ("incorporation", is_company_like(profile), "a company" if is_company_like(profile) else "not a company")]
    rows = []
    for key, required, why in spec:
        label, accepted, link = DOCS[key]
        if key == "bank_document" and india and ifsc:
            link = ("Bank and branch for this IFSC", f"https://ifsc.razorpay.com/{ifsc}")
        if key == "tax_form" and country in cn.SITES:
            link = cn.SITES[country]
        hits = [h for t in accepted for h in pages.get(t, [])]
        own = [h for h in hits if not h["foreign"]]
        if own:
            first = own[0]
            state, where = "found", f"{first['file']} p.{first['page']}" + (f" (+{len(own) - 1} more)" if len(own) > 1 else "")
        elif hits:
            state, where = "other_party", f"{hits[0]['file']} p.{hits[0]['page']} is in the name of {hits[0]['foreign']}"
        else:
            state, where = ("missing" if required else "not_required"), ""
        if not required and state == "missing":
            state = "not_required"
        rows.append(Row(key, label, required, why, state, where, link, [(h["file"], h["page"]) for h in own]))
    return rows


def missing(rows: list[Row]) -> list[Row]:
    return [r for r in rows if r.required and r.state in ("missing", "other_party")]
