"""Which tax ID belongs to which country, and whether bank details fit a country. Pure functions: no I/O, no network.

India gets deep verification elsewhere (GST, PAN, IFSC, MCA). For every other country we can only check what an ID
SHOULD look like (shape and, where one exists, the checksum) and whether it belongs to the country the vendor claims.
We never present that as verification against a government register."""
import re
from dataclasses import dataclass, field

from . import validators as v

EU = {"AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "HR": "Croatia", "CY": "Cyprus", "CZ": "Czechia", "DK": "Denmark", "EE": "Estonia",
      "FI": "Finland", "FR": "France", "DE": "Germany", "GR": "Greece", "HU": "Hungary", "IE": "Ireland", "IT": "Italy", "LV": "Latvia",
      "LT": "Lithuania", "LU": "Luxembourg", "MT": "Malta", "NL": "Netherlands", "PL": "Poland", "PT": "Portugal", "RO": "Romania",
      "SK": "Slovakia", "SI": "Slovenia", "ES": "Spain", "SE": "Sweden"}
COUNTRIES = {"IN": "India", "US": "United States", "GB": "United Kingdom", "CA": "Canada", "AU": "Australia", "SG": "Singapore",
             "AE": "United Arab Emirates", **EU}
VAT_RE = {"AT": r"ATU\d{8}", "BE": r"BE[01]\d{9}", "BG": r"BG\d{9,10}", "HR": r"HR\d{11}", "CY": r"CY\d{8}[A-Z]", "CZ": r"CZ\d{8,10}",
          "DK": r"DK\d{8}", "EE": r"EE\d{9}", "FI": r"FI\d{8}", "FR": r"FR[0-9A-Z]{2}\d{9}", "DE": r"DE\d{9}", "GR": r"EL\d{9}", "HU": r"HU\d{8}",
          "IE": r"IE\d[A-Z0-9+*]\d{5}[A-Z]{1,2}", "IT": r"IT\d{11}", "LV": r"LV\d{11}", "LT": r"LT(\d{9}|\d{12})", "LU": r"LU\d{8}", "MT": r"MT\d{8}",
          "NL": r"NL\d{9}B\d{2}", "PL": r"PL\d{10}", "PT": r"PT\d{9}", "RO": r"RO\d{2,10}", "SK": r"SK\d{10}", "SI": r"SI\d{8}",
          "ES": r"ES[A-Z0-9]\d{7}[A-Z0-9]", "SE": r"SE\d{12}"}
EXAMPLE = {"IN": "GSTIN such as 33AAACZ4322M1ZA", "US": "EIN such as 12-3456789", "GB": "VAT number such as GB123456789", "CA": "Business Number such as 123456789RT0001",
           "AU": "ABN such as 51 824 753 556", "SG": "UEN such as 201234567A", "AE": "TRN such as 100123456700003"}
for _c in EU:
    EXAMPLE[_c] = f"VAT number such as {'EL' if _c == 'GR' else _c}123456789"
# where a person can check the number themselves (we cannot call these automatically)
SITES = {"US": ("IRS: TIN matching and Form W-9 (needs an IRS e-Services account)", "https://www.irs.gov/tin-matching"),
         "GB": ("HMRC: check a UK VAT number", "https://www.gov.uk/check-uk-vat-number"),
         "CA": ("CRA: GST/HST registry search", "https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-businesses/gst-hst-registry-search.html"),
         "AU": ("ABN Lookup", "https://abr.business.gov.au/"), "SG": ("UEN search (data.gov.sg / ACRA)", "https://www.uen.gov.sg/ueninternet/faces/pages/admin/aceSearch.jspx"),
         "AE": ("UAE Federal Tax Authority: TRN verification", "https://tax.gov.ae/en/default.aspx"),
         **{c: ("EU VIES: check a VAT number", "https://ec.europa.eu/taxation_customs/vies/") for c in EU}}
INVALID_EIN_PREFIX = {"00", "07", "08", "09", "17", "18", "19", "28", "29", "49", "69", "70", "78", "79", "89", "96", "97"}
IBAN_LEN = {"AT": 20, "BE": 16, "BG": 22, "HR": 21, "CY": 28, "CZ": 24, "DK": 18, "EE": 20, "FI": 18, "FR": 27, "DE": 22, "GR": 27, "HU": 28, "IE": 22,
            "IT": 27, "LV": 21, "LT": 20, "LU": 20, "MT": 31, "NL": 18, "PL": 28, "PT": 25, "RO": 24, "SK": 24, "SI": 19, "ES": 24, "SE": 24, "GB": 22,
            "CH": 21, "NO": 15, "AE": 23, "SA": 24}


ADJ = {"IN": "Indian", "US": "US", "GB": "UK", "CA": "Canadian", "AU": "Australian", "SG": "Singaporean", "AE": "UAE", "AT": "Austrian", "BE": "Belgian",
       "BG": "Bulgarian", "HR": "Croatian", "CY": "Cypriot", "CZ": "Czech", "DK": "Danish", "EE": "Estonian", "FI": "Finnish", "FR": "French",
       "DE": "German", "GR": "Greek", "HU": "Hungarian", "IE": "Irish", "IT": "Italian", "LV": "Latvian", "LT": "Lithuanian", "LU": "Luxembourg",
       "MT": "Maltese", "NL": "Dutch", "PL": "Polish", "PT": "Portuguese", "RO": "Romanian", "SK": "Slovak", "SI": "Slovenian", "ES": "Spanish", "SE": "Swedish"}


def describe(m: "Match") -> str:
    """'an Indian GSTIN', 'a US EIN', 'a German VAT number'."""
    adj = ADJ.get(m.country, name_of(m.country))
    an = adj[:1] in "AEIOU" and adj not in ("US", "UK", "UAE")          # "a US EIN", "a UK VAT number", "an Indian GSTIN"
    return f"{'an' if an else 'a'} {adj} {m.id_type}"


def name_of(code: str) -> str:
    return COUNTRIES.get(code, code or "an unknown country")


def flat(value: str | None) -> str:
    return re.sub(r"[\s\-.,]", "", (value or "")).upper()


@dataclass
class Match:
    country: str
    id_type: str
    strong: bool = True            # a prefix or checksum identifies it; digits-only numbers are weak (many countries share 9 digits)
    valid: bool = True             # passes its checksum, where one exists
    note: str = ""


def _gb_vat_ok(d: str) -> bool:
    """HMRC modulus 97 check on 9-digit VAT numbers (accepts both the old and the 2010+ variant)."""
    if len(d) < 9 or not d[:9].isdigit():
        return False
    total = sum(int(c) * w for c, w in zip(d[:7], (8, 7, 6, 5, 4, 3, 2))) + int(d[7:9])
    return total % 97 == 0 or (total + 55) % 97 == 0


def abn_ok(d: str) -> bool:
    if not re.fullmatch(r"\d{11}", d):
        return False
    digits = [int(c) for c in d]
    digits[0] -= 1
    return sum(x * w for x, w in zip(digits, (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19))) % 89 == 0


def detect(value: str | None) -> list[Match]:
    """Every country/ID-type this value could be. Strong matches first."""
    x = flat(value)
    out: list[Match] = []
    if not x:
        return out
    if len(x) == 15 and v.GSTIN_SHAPE_RE.match(x) or (len(x) == 15 and re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]", x)):
        out.append(Match("IN", "GSTIN", True, v.check_gstin(x).code in ("", "sandbox", "tax_collector", "tax_deductor", "reg_type")))
    if v.PAN_RE.match(x):
        out.append(Match("IN", "PAN", True))
    if v.CIN_RE.match(x):
        out.append(Match("IN", "CIN", True))
    for c, rx in VAT_RE.items():
        if re.fullmatch(rx, x):
            out.append(Match(c, "VAT number", True))
    if re.fullmatch(r"GB(\d{9}|\d{12}|GD\d{3}|HA\d{3})", x):
        out.append(Match("GB", "VAT number", True, _gb_vat_ok(x[2:]) if re.fullmatch(r"GB\d{9}", x) else True))
    if re.fullmatch(r"\d{3}-?\d{2}-?\d{4}", (value or "").strip()) and "-" in (value or ""):
        out.append(Match("US", "SSN/ITIN (a personal ID)", True, note="personal"))
    if re.fullmatch(r"\d{2}-\d{7}", (value or "").strip()):
        out.append(Match("US", "EIN", True, x[:2] not in INVALID_EIN_PREFIX))
    elif re.fullmatch(r"\d{9}", x):
        out.append(Match("US", "EIN", False, x[:2] not in INVALID_EIN_PREFIX))
        out.append(Match("CA", "Business Number", False))
        if _gb_vat_ok(x):
            out.append(Match("GB", "VAT number", False))
    if re.fullmatch(r"\d{9}RT\d{4}", x):
        out.append(Match("CA", "GST/HST Business Number", True))
    if re.fullmatch(r"\d{11}", x) and abn_ok(x):
        out.append(Match("AU", "ABN", True))
    if re.fullmatch(r"(\d{8,9}[A-Z]|[TS]\d{2}[A-Z]{2}\d{4}[A-Z])", x):
        out.append(Match("SG", "UEN", True))
    if re.fullmatch(r"\d{15}", x):
        out.append(Match("AE", "TRN", True))
    out.sort(key=lambda m: not m.strong)
    return out


@dataclass
class TaxCheck:
    ok: bool
    code: str = ""                 # ok | wrong_country | invalid | unrecognised | personal
    message: str = ""
    found: list[Match] = field(default_factory=list)
    id_type: str = ""


def check_tax_id(country: str, value: str) -> TaxCheck:
    """Does this ID look right FOR THE CLAIMED COUNTRY? (Shape/checksum only, never a register lookup.)"""
    found = detect(value)
    if country not in COUNTRIES:                     # a country we hold no format rules for: say so, never reject it
        return TaxCheck(True, "ok", "We hold no format rules for this country, so the tax ID cannot be checked automatically.", found, "tax ID")
    mine = [m for m in found if m.country == country]
    cname = name_of(country)
    if any(m.note == "personal" for m in found):
        return TaxCheck(False, "personal", "This looks like a personal ID (SSN/ITIN). Do not send personal IDs: send the business's tax ID (EIN).", found)
    if mine:
        good = [m for m in mine if m.valid]
        if good:
            return TaxCheck(True, "ok", f"Format is valid for {cname} ({good[0].id_type}). This is a format check only; no register was consulted.", found, good[0].id_type)
        return TaxCheck(False, "invalid", f"The number has the shape of a {cname} {mine[0].id_type} but fails its check digit, so it has a typing error.", found, mine[0].id_type)
    strong = [m for m in found if m.strong]
    if strong:
        m = strong[0]
        return TaxCheck(False, "wrong_country", f"This looks like {describe(m)}, but the vendor says it is based in {cname}.", found, m.id_type)
    if found:
        m = found[0]
        return TaxCheck(False, "wrong_country", f"This could be {describe(m)}, but the vendor says it is based in {cname}.", found, m.id_type)
    return TaxCheck(False, "unrecognised", f"This is not a recognised {cname} tax ID format. Expected: {EXAMPLE.get(country, 'the local tax ID')}.", found)


def _a(name: str) -> str:
    return ("an " if name[:1] in "AEIOU" else "a ") + name


def infer_country(values: dict) -> str:
    """The country the identifiers point to, when the vendor did not say: Indian IDs mean India; otherwise a single clear match."""
    if any(values.get(k) for k in ("gstin", "pan", "cin", "ifsc")):
        return "IN"
    countries = {m.country for k in ("tax_id",) if values.get(k) for m in detect(values[k]) if m.strong}
    if len(countries) == 1:
        return countries.pop()
    iban = flat(values.get("iban") or values.get("bank_account"))
    if re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban) and iban[:2] in IBAN_LEN and iban_ok(iban):
        return iban[:2]
    return ""


# ---------- bank details outside India ----------

def iban_ok(iban: str) -> bool:
    x = flat(iban)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", x) or IBAN_LEN.get(x[:2]) not in (None, len(x)):
        return False
    rearranged = x[4:] + x[:4]
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


def aba_ok(routing: str) -> bool:
    d = re.sub(r"\D", "", routing or "")
    return len(d) == 9 and (3 * (int(d[0]) + int(d[3]) + int(d[6])) + 7 * (int(d[1]) + int(d[4]) + int(d[7])) + (int(d[2]) + int(d[5]) + int(d[8]))) % 10 == 0


SWIFT_RE = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$")


@dataclass
class BankIssue:
    field: str                     # iban | bank_account | routing_code | swift
    code: str
    message: str


def check_foreign_bank(country: str, bank_account: str = "", iban: str = "", routing_code: str = "", swift: str = "") -> list[BankIssue]:
    """Is this bank detail set well-formed and consistent with the claimed country? Empty list = fine."""
    issues: list[BankIssue] = []
    cname = name_of(country)
    acct = flat(bank_account)
    iban_val = flat(iban) or (acct if re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", acct) else "")
    sw = flat(swift)
    if country in IBAN_LEN or iban_val:
        if not iban_val:
            issues.append(BankIssue("iban", "missing", f"Banks in {cname} use an IBAN: please give the IBAN."))
        elif not iban_ok(iban_val):
            issues.append(BankIssue("iban", "invalid", "The IBAN fails its check digits or has the wrong length for its country, so it has a typing error."))
        elif country in IBAN_LEN and iban_val[:2] != country:
            issues.append(BankIssue("iban", "wrong_country", f"The IBAN starts with {iban_val[:2]} ({name_of(iban_val[:2])}), but the vendor says it is based in {cname}."))
    elif country == "US":
        if not routing_code or not aba_ok(routing_code):
            issues.append(BankIssue("routing_code", "invalid" if routing_code else "missing", "A US bank needs a valid 9-digit ABA routing number."
                                    if not routing_code else "The ABA routing number fails its check digit, so it has a typing error."))
        if not re.fullmatch(r"\d{4,17}", acct):
            issues.append(BankIssue("bank_account", "invalid", "A US account number is 4 to 17 digits."))
    else:
        if not re.fullmatch(r"[A-Z0-9]{4,34}", acct):
            issues.append(BankIssue("bank_account", "invalid" if acct else "missing", "Please give the bank account number (4 to 34 letters or digits)."))
        if not sw and not routing_code:
            issues.append(BankIssue("swift", "missing", "Please give the bank's SWIFT/BIC code or local routing code."))
    if sw:
        if not SWIFT_RE.match(sw):
            issues.append(BankIssue("swift", "invalid", "A SWIFT/BIC is 8 or 11 characters: 4 letters (bank), 2 letters (country), 2 characters (place), optionally 3 (branch)."))
        elif country in COUNTRIES and sw[4:6] != country and not (country == "GR" and sw[4:6] == "GR"):
            issues.append(BankIssue("swift", "wrong_country", f"The SWIFT/BIC is for {name_of(sw[4:6])}, but the vendor says it is based in {cname}."))
    return issues
