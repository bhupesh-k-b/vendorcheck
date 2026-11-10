"""Offline validators and name logic. Pure functions, no I/O, no network.

Everything here is deterministic. The model never decides a status or fills in a digit."""
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
PAN_RE = re.compile(r"^[A-Z]{3}[ABCFGHLJPT][A-Z][0-9]{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
CIN_RE = re.compile(r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")
GSTIN_SHAPE_RE = re.compile(r"^[0-9]{2}[A-Z]{3}[ABCFGHLJPT][A-Z][0-9]{4}[A-Z][1-9A-Z][A-Z0-9][A-Z0-9]$")
ACCOUNT_RE = re.compile(r"^[0-9]{9,18}$")
UDYAM_RE = re.compile(r"^UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}$")

SANDBOX_GSTIN = "00AAAAA0000A1ZT"   # gstinapi.in's free fixed-sample GSTIN

STATES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura",
    "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
    "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat", "26": "Dadra & Nagar Haveli and Daman & Diu",
    "27": "Maharashtra", "28": "Andhra Pradesh (old)", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman & Nicobar Islands",
    "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction",
}
# CIN state letters -> state name, for the (advisory) registered-office comparison.
CIN_STATES = {"DL": "Delhi", "TN": "Tamil Nadu", "KA": "Karnataka", "MH": "Maharashtra", "GJ": "Gujarat",
              "HR": "Haryana", "UP": "Uttar Pradesh", "TG": "Telangana", "AP": "Andhra Pradesh", "WB": "West Bengal",
              "KL": "Kerala", "RJ": "Rajasthan", "PB": "Punjab", "MP": "Madhya Pradesh", "OR": "Odisha", "CH": "Chandigarh"}

PAN_TYPES = {"C": "company", "P": "individual / proprietor", "F": "firm / LLP", "H": "HUF", "A": "association of persons",
             "B": "body of individuals", "G": "government", "J": "artificial juridical person", "L": "local authority", "T": "trust"}


def clean(value: str | None) -> str:
    """Uppercase and strip whitespace/hyphens from an identifier."""
    return re.sub(r"[\s\-]", "", (value or "")).upper()


def gstin_check_char(first14: str) -> str:
    total = 0
    for i, c in enumerate(first14):
        p = ALPHABET.index(c) * (1 if i % 2 == 0 else 2)
        total += p // 36 + p % 36
    return ALPHABET[(36 - total % 36) % 36]


def with_gstin_check_char(first14: str) -> str:
    return first14 + gstin_check_char(first14)


@dataclass
class Result:
    ok: bool
    code: str = ""        # machine-readable reason
    message: str = ""     # plain-language reason


def check_gstin(value: str | None) -> Result:
    """R06: format, check digit, registration type. Order matters: the first failure is reported."""
    g = clean(value)
    if len(g) != 15 or not re.fullmatch(r"[0-9A-Z]{15}", g):
        return Result(False, "format", "A GSTIN has exactly 15 letters and digits.")
    if g == SANDBOX_GSTIN:
        return Result(True, "sandbox")
    if g[:2] not in STATES:
        return Result(False, "state", f"State code {g[:2]} is not a valid GST state code.")
    if not GSTIN_SHAPE_RE.match(g):
        return Result(False, "shape", "The characters do not follow the GSTIN pattern (state, PAN, entity number, Z, check character).")
    if g[14] != gstin_check_char(g[:14]):
        return Result(False, "check_digit", "The last character does not match the GSTIN check digit, so there is a typing error.")
    t = g[13]
    if t == "C":
        return Result(False, "tax_collector", "The 14th character is C: this is a tax-collector (TCS) registration. It cannot appear on supply invoices.")
    if t == "D":
        return Result(False, "tax_deductor", "The 14th character is D: this is a tax-deductor (TDS) registration. It cannot appear on supply invoices.")
    if t != "Z":
        return Result(False, "reg_type", f"The 14th character should be Z for a regular registration, found {t}.")
    return Result(True)


def pan_from_gstin(gstin: str) -> str:
    return clean(gstin)[2:12]


def state_of_gstin(gstin: str) -> str:
    return STATES.get(clean(gstin)[:2], "")


def check_pan(value: str | None) -> Result:
    p = clean(value)
    if not PAN_RE.match(p):
        return Result(False, "format", "A PAN is 10 characters: 5 letters, 4 digits, 1 letter (4th letter shows the holder type).")
    return Result(True)


def pan_type(pan: str) -> str:
    return PAN_TYPES.get(clean(pan)[3:4], "")


def entity_kind_from_name(name: str) -> str | None:
    """Offline guess of the constitution from a legal name: 'C', 'F' or None when it cannot be told."""
    n = normalise_name(name)
    if re.search(r"\bLLP\b|LIMITED LIABILITY PARTNERSHIP", n):
        return "F"
    if re.search(r"\bLIMITED$", n):
        return "C"
    return None


def check_pan_constitution(pan: str, name: str | None = None, cin: str | None = None) -> Result:
    """R07: the 4th character must fit what we can tell about the entity (company C, firm/LLP F, person P)."""
    p = clean(pan)
    expected = "C" if clean(cin) else entity_kind_from_name(name or "")
    if expected and len(p) >= 4 and p[3] != expected:
        return Result(False, "constitution",
                      f"4th character of the PAN is {p[3]} ({PAN_TYPES.get(p[3], 'unknown')}) but the vendor looks like a "
                      f"{PAN_TYPES[expected]}.")
    return Result(True)


def check_ifsc_format(value: str | None) -> Result:
    if not IFSC_RE.match(clean(value)):
        return Result(False, "format", "An IFSC is 11 characters: 4 letters, a zero, then 6 letters or digits.")
    return Result(True)


def check_cin(value: str | None, name: str | None = None) -> Result:
    """R10: format, and the ownership class (PTC/PLC) must fit the company name."""
    c = clean(value)
    if not CIN_RE.match(c):
        return Result(False, "format", "A CIN is 21 characters: L or U, 5 digits, 2 letters, 4 digits, 3 letters, 6 digits.")
    cls = c[12:15]
    n = normalise_name(name or "")
    if n.endswith("PRIVATE LIMITED") and cls not in {"PTC", "OPC", "FTC"}:
        return Result(False, "class", f"The name says private limited but the CIN class is {cls}, not PTC.")
    if n.endswith("LIMITED") and not n.endswith("PRIVATE LIMITED") and cls not in {"PLC", "NPL", "GOI", "SGC", "ULL", "ULT"}:
        return Result(False, "class", f"The name says public limited but the CIN class is {cls}, not PLC.")
    return Result(True)


def check_account(account: str | None, confirmation: str | None = None) -> Result:
    a = re.sub(r"\s", "", account or "")
    if not ACCOUNT_RE.match(a):
        return Result(False, "format", "An account number is 9 to 18 digits.")
    if confirmation is not None and re.sub(r"\s", "", confirmation) != a:
        return Result(False, "mismatch", "The account number and its confirmation do not match.")
    return Result(True)


def clean_udyam(value: str | None) -> str:
    """Uppercase and remove spaces only: unlike other identifiers a Udyam number keeps its hyphens (UDYAM-MH-26-0012345)."""
    return re.sub(r"\s", "", value or "").upper()


def check_udyam(value: str | None) -> Result:
    if not UDYAM_RE.match(clean_udyam(value)):
        return Result(False, "format", "A Udyam number looks like UDYAM-TN-00-0000000.")
    return Result(True)


# ---------- names ----------

def normalise_name(name: str | None) -> str:
    """Uppercase, strip punctuation, drop M/S, map PVT->PRIVATE, LTD->LIMITED, &->AND, collapse spaces."""
    n = (name or "").upper()
    n = n.replace("&", " AND ")
    n = re.sub(r"^\s*M\s*/\s*S\.?\s+", "", n)
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    n = re.sub(r"\bPVT\b", "PRIVATE", n)
    n = re.sub(r"\bLTD\b", "LIMITED", n)
    return re.sub(r"\s+", " ", n).strip()


def name_score(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    na, nb = normalise_name(a), normalise_name(b)
    # OCR of scans often drops the spaces between words, so also compare with all spaces removed
    return float(max(fuzz.token_sort_ratio(na, nb), fuzz.ratio(na.replace(" ", ""), nb.replace(" ", ""))))


def names_match(a: str | None, b: str | None, threshold: float = 92) -> bool:
    return name_score(a, b) >= threshold


# ---------- masking ----------

def mask(value: str | None, keep: int = 4) -> str:
    v = value or ""
    if len(v) <= keep:
        return v
    return "•" * (len(v) - keep) + v[-keep:]
