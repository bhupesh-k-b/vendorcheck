"""Deterministic document understanding: no model, no network, no tokens.

Given the text of one page (a PDF text layer or OCR output) it decides what kind of document(s) the page holds and
pulls out identifiers with regexes and checksums, and names by their printed labels. Anything it cannot settle is
reported as `missing`, and only then may the caller ask a language model about THAT page's text."""
import re

from . import validators as v

# document type -> (patterns, how many must match)
CLASSIFY = {
    "pan_card": ([r"INCOME\s*TAX\s*DEPARTMENT", r"PERMANENT\s*ACCOUNT\s*NUMBER", r"GOVT\.?\s*OF\s*INDIA"], 2),
    "gst_certificate": ([r"REGISTRATION\s*CERTIFICATE", r"GST\s*REG", r"LEGAL\s*NAME", r"CONSTITUTION\s*OF\s*BUSINESS", r"DATE\s*OF\s*LIABILITY"], 3),
    "incorporation_or_name_change_certificate": ([r"CERTIFICATE\s*OF\s*INCORPORATION", r"HEREBY\s*CERTIFY", r"CORPORATE\s*IDENTITY\s*NUMBER",
                                                  r"CHANGE\s*OF\s*NAME", r"REGISTRAR\s*OF\s*COMPANIES", r"ARTICLES\s*OF\s*(ORGANI[ZS]ATION|INCORPORATION)",
                                                  r"CERTIFICATE\s*OF\s*(FORMATION|GOOD\s*STANDING)", r"HANDELSREGISTER|COMMERCIAL\s*REGISTER|TRADE\s*REGISTER",
                                                  r"LIMITED\s*LIABILITY\s*COMPANY|\bLLC\b", r"DATE\s*OF\s*FORMATION|REGISTERED\s*(OFFICE|AGENT)",
                                                  r"RECHTSFORM|\bSITZ\b|GESELLSCHAFT\s*MIT"], 2),
    "stock_exchange_filing": ([r"REGULATION\s*30", r"SCRIP\s*(CODE|SYMBOL)", r"STOCK\s*EXCHANGE", r"\bNSE\b|\bBSE\b", r"LISTING\s*REGULATIONS"], 2),
    "cancelled_cheque_or_bank_letter": ([r"\bPAY\b", r"A\s*/?\s*C\.?\s*NO", r"CANCELL?ED", r"\bIFSC?\b|\bIFS\s*CODE", r"OR\s*ORDER", r"CHEQUE", r"BANK\s*(ACCOUNT\s*)?CONFIRMATION", r"TO\s*WHOM\s*IT\s*MAY\s*CONCERN",
                                         r"ACCOUNT\s*HOLDER", r"\bIBAN\b", r"ROUTING\s*(NO|NUMBER)"], 3),
    "bank_details_form": ([r"NEFT", r"RTGS", r"BANK\s*A\s*/?\s*C", r"IFSC", r"NAME\s*OF\s*THE\s*BANK"], 3),
    "udyam_certificate": ([r"UDYAM\s*REGISTRATION\s*CERTIFICATE", r"UDYAM-[A-Z]{2}-\d{2}-\d{7}", r"MICRO,?\s*SMALL\s*AND\s*MEDIUM"], 2),
    "tax_filing_document": ([r"INCOME\s*TAX\s*RETURN|\bITR-?\s*\d|ACKNOWLEDGEMENT\s*NUMBER", r"\bGSTR-?\s*\d", r"ASSESSMENT\s*YEAR", r"\bCHALLAN\b", r"FORM\s*26AS|\bTDS\b"], 2),
    "address_proof": ([r"ELECTRICITY\s*BILL|UTILITY\s*BILL|WATER\s*BILL|TELEPHONE\s*BILL|PROPERTY\s*TAX", r"CONSUMER\s*(NO|NUMBER)|SERVICE\s*CONNECTION",
                       r"RENT\s*AGREEMENT|LEASE\s*DEED", r"BILLING\s*PERIOD|AMOUNT\s*DUE|UNITS\s*CONSUMED"], 2),
    "other_certificate": ([r"ISO\s*(9001|14001|45001)", r"POLLUTION\s*(CONTROL)?", r"CERTIFICATE\s*OF\s*REGISTRATION", r"LICEN[CS]E\s*NO"], 1),
    "vendor_registration_form": ([r"VENDOR\s*REGISTRATION", r"NAME\s*OF\s*THE\s*COMPANY\s*/?\s*VENDOR"], 1),
    "tax_form_or_vat_certificate": ([r"\bW-?\s*9\b", r"\bW-?\s*8\s*BEN", r"REQUEST\s*FOR\s*TAXPAYER\s*IDENTIFICATION", r"VAT\s*REGISTRATION", r"CERTIFICATE\s*OF\s*VAT",
                                    r"VAT\s*(NO|NUMBER|REG)", r"TAX\s*REGISTRATION\s*CERTIFICATE", r"EMPLOYER\s*IDENTIFICATION\s*NUMBER", r"\bABN\b"], 2),
}
# which fields a page of each type must yield before we trust the rules without asking anyone
NEEDS = {"pan_card": ["pan", "legal_name"], "gst_certificate": ["gstin", "legal_name"], "incorporation_or_name_change_certificate": ["cin", "legal_name"],
         "cancelled_cheque_or_bank_letter": ["bank_account"], "bank_details_form": ["bank_account", "account_holder"], "vendor_registration_form": []}

GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z][A-Z][0-9A-Z]\b")
PAN_RE = re.compile(r"(?<![A-Z0-9])[A-Z]{5}\d{4}[A-Z](?![A-Z0-9])")
CIN_RE = re.compile(r"\b[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b")
IFSC_RE = re.compile(r"(?<![A-Z0-9])[A-Z]{4}0[A-Z0-9]{6}(?![A-Z0-9])")
LABEL_WORD = re.compile(r"^(service|billing|type|major|date|consumer|account|units|amount|address|name|registered|firma|sitz|business|federal|employer|gstin|pan|legal|trade)\b", re.I)
UDYAM_RE = re.compile(r"UDYAM-[A-Z]{2}-\d{2}-\d{7}", re.I)
PIN_RE = re.compile(r"(?<!\d)[1-9]\d{5}(?!\d)")
DIAL = {"+91": "IN", "+1": "US", "+44": "GB", "+49": "DE", "+33": "FR", "+39": "IT", "+34": "ES", "+31": "NL", "+65": "SG", "+61": "AU",
        "+971": "AE", "+353": "IE", "+46": "SE", "+48": "PL"}
COUNTRY_WORDS = {"IN": r"\bINDIA\b", "US": r"\bUNITED\s*STATES\b|\bU\.?S\.?A\b", "GB": r"\bUNITED\s*KINGDOM\b|\bENGLAND\b", "DE": r"\bGERMANY\b|\bDEUTSCHLAND\b",
                 "FR": r"\bFRANCE\b", "IT": r"\bITALY\b|\bITALIA\b", "ES": r"\bSPAIN\b", "NL": r"\bNETHERLANDS\b", "SG": r"\bSINGAPORE\b", "AU": r"\bAUSTRALIA\b",
                 "AE": r"\bUNITED\s*ARAB\s*EMIRATES\b|\bDUBAI\b", "CA": r"\bCANADA\b", "IE": r"\bIRELAND\b", "SE": r"\bSWEDEN\b", "PL": r"\bPOLAND\b"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def country_hints(text: str) -> list[str]:
    """Countries a page points to by name or by phone dialling code (identifiers are judged separately, by their shape)."""
    found = [c for c, rx in COUNTRY_WORDS.items() if re.search(rx, text or "", re.I)]
    for code, c in DIAL.items():
        if re.search(r"(?<![\d+])" + re.escape(code) + r"[\s\-(]?\d", text or "") and c not in found:
            found.append(c)
    return found


def block_after(label_re: str, text: str, maxlen: int = 220) -> str:
    """Up to three lines after a label (an address), stopping at the next numbered or labelled item."""
    m = re.search(r"(?:" + label_re + r")[ \t]*[:\-]?[ \t]*\n?", text, re.I)
    if not m:
        return ""
    lines = []
    for ln in text[m.end(): m.end() + maxlen].split("\n"):
        if re.match(r"\s*\d\.\s", ln) or re.match(r"\s*(consumer|account|bill|units|date|amount|meter|name)\b", ln, re.I):
            break
        if ln.strip():
            lines.append(ln.strip())
        if len(lines) >= 3:
            break
    return " ".join(lines).strip(" :-")
PHONE_RE = re.compile(r"(?<!\d)[6-9]\d{9}(?!\d)")
SEP = r"[ \n]*[:.\-]?[ \n]*"          # the value may follow its label on the same line or on the next line
ACCOUNT_RES = [re.compile(r"A[ ]*/?[ ]*C\.?[ ]*(?:NO\.?|NUMBER)" + SEP + r"((?:\d[ ]?){9,18})", re.I),
               re.compile(r"ACCOUNT[ ]*(?:NO\.?|NUMBER)" + SEP + r"((?:\d[ ]?){9,18})", re.I),
               re.compile(r"BANK[ ]*A[ ]*/?[ ]*C\.?[ ]*NO\.?" + SEP + r"((?:\d[ ]?){9,18})", re.I)]   # the digits themselves stay on one line
NAME_CHARS = r"[A-Za-z0-9&.,'()/\- ]"


TAX_LABEL_RE = re.compile(r"(?:\bEIN\b|\bTIN\b|\bVAT(?:[ ]*(?:NO\.?|NUMBER|REG\w*|ID))?|TAX[ ]*ID|TAX[ ]*REG\w*[ ]*(?:NO\.?|NUMBER)?|\bABN\b|\bUEN\b|\bTRN\b|BUSINESS[ ]*NUMBER|"
                          r"EMPLOYER[ ]*IDENTIFICATION[ ]*NUMBER)[ \n:.#\-]{0,6}([A-Z0-9][A-Z0-9 .\-]{7,22}[A-Z0-9])", re.I)
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{3,4}){2,8}\b")
SWIFT_LABEL_RE = re.compile(r"(?:SWIFT|BIC)(?:[ /]*(?:BIC|CODE))?[ \n:.#\-]{0,6}([A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b", re.I)
ROUTING_RE = re.compile(r"(?:ABA|ROUTING)[ ]*(?:NO\.?|NUMBER|#)?[ \n:.#\-]{0,6}(\d{9})\b|SORT[ ]*CODE[ \n:.#\-]{0,6}(\d{2}-?\d{2}-?\d{2})\b", re.I)


def foreign_identifiers(text: str) -> dict[str, str]:
    """Non-Indian tax number, IBAN, SWIFT and routing code on the page, validated by shape so label noise is not taken for an ID."""
    from . import countries as cn
    t = _norm(text)
    out: dict[str, str] = {}
    for m in TAX_LABEL_RE.finditer(t):
        cand = m.group(1).strip()
        if cn.detect(cand) and not GSTIN_RE.fullmatch(cn.flat(cand)):
            out["tax_id"] = cand
            break
    if "tax_id" not in out:
        m = re.search(r"(?<!\d)\d{2}-\d{7}(?!\d)", t)
        if m:
            out["tax_id"] = m.group(0)
    for m in IBAN_RE.finditer(t.upper()):
        if cn.iban_ok(m.group(0)):
            out["iban"] = cn.flat(m.group(0))
            break
    if (m := SWIFT_LABEL_RE.search(t)):
        out["swift"] = m.group(1).upper()
    if (m := ROUTING_RE.search(t)):
        out["routing_code"] = (m.group(1) or m.group(2)).replace("-", "")
    return out


def _norm(t: str) -> str:
    return re.sub(r"[ \t]+", " ", t or "")


def classify(text: str) -> list[str]:
    """Every document type whose keywords appear on the page (a page can hold more than one document)."""
    up = text.upper()
    hits = []
    for dt, (pats, need) in CLASSIFY.items():
        if sum(1 for p in pats if re.search(p, up)) >= need:
            hits.append(dt)
    if "pan_card" in hits and "tax_filing_document" in hits:
        hits.remove("tax_filing_document")           # a PAN card says "Income Tax Department"
    if "stock_exchange_filing" in hits and "incorporation_or_name_change_certificate" in hits and re.search(r"REGULATION\s*30", up):
        hits.remove("incorporation_or_name_change_certificate")   # a filing that merely attaches a certificate
    return hits


def custom_types(text: str, custom: list[dict]) -> list[str]:
    """Keys of the documents you added (Settings) whose words appear on this page. Spaces are ignored on both sides, because text recognition drops them."""
    flat = re.sub(r"\s+", "", (text or "").upper())
    out = []
    for d in custom or []:
        hits = sum(1 for kw in d.get("keywords", []) if re.sub(r"\s+", "", kw.upper()) and re.sub(r"\s+", "", kw.upper()) in flat)
        if hits >= max(1, int(d.get("need", 1))):
            out.append(d["key"])
    return out


def custom_values(text: str, items: list[dict], types: list[str]) -> list[dict]:
    """The number of each item you added (format in Settings), found on a page where its document was recognised: the first run of up to five
    neighbouring words that fits the format. Returned as page-field candidates (x_<key>) typed to that document."""
    from .policy import format_ok
    out = []
    tokens = re.findall(r"[A-Z0-9/\-]+", (text or "").upper())
    for d in items or []:
        if not d.get("format") or d["key"] not in types:
            continue
        for i in range(len(tokens)):
            hit = next(("".join(tokens[i:i + n]) for n in range(1, 6) if format_ok(d["format"], "".join(tokens[i:i + n]))), None)
            if hit:
                out.append({"field": "x_" + d["key"], "value": re.sub(r"[\s\-]", "", hit), "doc_type": d["key"], "snippet": hit})
                break
    return out


def identifiers(text: str) -> dict[str, list[str]]:
    """Every identifier-shaped token on the page, in reading order, de-duplicated."""
    up = _norm(text).upper()
    gst = list(dict.fromkeys(GSTIN_RE.findall(up)))
    masked = GSTIN_RE.sub(" ", up)                                  # a GSTIN contains a PAN: do not count it as a separate PAN
    out = {"gstin": gst, "pan": list(dict.fromkeys(PAN_RE.findall(masked))), "cin": list(dict.fromkeys(CIN_RE.findall(up))),
           "ifsc": list(dict.fromkeys(IFSC_RE.findall(masked)))}
    acc: list[str] = []
    for rx in ACCOUNT_RES:
        for m in rx.finditer(_norm(text)):
            digits = re.sub(r"\D", "", m.group(1))
            if 9 <= len(digits) <= 18 and digits not in acc:
                acc.append(digits)
    out["bank_account"] = acc
    return out


def _after(label_re: str, text: str, stop=r"[\n]") -> str:
    """The value printed after a label on the same line, or on the next non-empty line."""
    m = re.search(r"(?:" + label_re + r")\s*[:\-]?\s*(" + NAME_CHARS + r"*)", text, re.I)      # group the label: it may contain alternatives
    if not m:
        return ""
    val = m.group(1).strip(" :-")
    if len(val) >= 3:
        return val
    rest = text[m.end():].lstrip(" \n")
    return rest.split("\n", 1)[0].strip(" :-")


def names(text: str, doc_type: str) -> dict[str, str]:
    """Names by their printed labels, per document type. Empty when the label is not there."""
    t = text
    out: dict[str, str] = {}
    if doc_type == "vendor_registration_form":
        if (n := _after(r"NAME\s*OF\s*THE\s*COMPANY\s*/?\s*VENDOR", t)):
            out["legal_name"] = n
        if (a := _after(r"REGD\.?\s*OFFICE", t)):
            out["address"] = a
        if (n := _after(r"NAME\s*OF\s*BANKERS[^:\n]*", t)) and False:
            out["bank_name"] = n
    elif doc_type == "pan_card":
        m = re.search(r"\n\s*NAME\s*\n\s*([A-Za-z0-9&.,'() \-]{4,})", t, re.I) or re.search(r"\bNAME\b\s*[:\-]?\s*([A-Za-z0-9&.,'() \-]{4,})", t, re.I)
        if m:
            out["legal_name"] = m.group(1).strip().split("  ")[0]
    elif doc_type == "address_proof":
        if (a := block_after(r"(?:SERVICE|BILLING|SUPPLY|PREMISES|REGISTERED)?[ ]*ADDRESS", t)):
            out["address"] = a
        if (n := _after(r"(?:CONSUMER|CUSTOMER|ACCOUNT)[ ]*NAME|NAME\s*OF\s*(?:THE\s*)?(?:CONSUMER|CUSTOMER)|BILLED\s*TO", t)):
            out["legal_name"] = n
    elif doc_type == "tax_form_or_vat_certificate":
        if (n := _after(r"(?:NAME\s*\(AS\s*SHOWN\s*ON\s*YOUR\s*INCOME\s*TAX\s*RETURN\)|LEGAL\s*NAME|REGISTERED\s*NAME|BUSINESS\s*NAME|COMPANY\s*NAME)", t)):
            out["legal_name"] = n
    elif doc_type == "gst_certificate":
        if (n := _after(r"(?:\d\.\s*)?LEGAL\s*NAME", t)):
            out["legal_name"] = n
        if (a := block_after(r"(?:\d\.\s*)?ADDRESS\s*OF\s*PRINCIPAL\s*PLACE\s*OF\s*BUSINESS", t)):
            out["address"] = a
        if (n := _after(r"TRADE\s*NAME[^\n:]*", t)):
            out["trade_name"] = n
    elif doc_type == "incorporation_or_name_change_certificate":
        m = re.search(r"HEREBY\s*CERTIFY\s*THAT\s*[\s,:]*([A-Z][A-Z0-9&.,'() \-]{6,}?(?:LIMITED|LTD\.?|LLP|PRIVATE LIMITED))", t, re.I)
        if m:
            out["legal_name"] = m.group(1).strip()
        elif (n := _after(r"(?:NAME\s*OF\s*(?:THE\s*)?(?:LLC|COMPANY|CORPORATION|ENTITY)|FIRMA|COMPANY\s*NAME)", t)):
            out["legal_name"] = n                       # US articles of organization, German commercial-register extract
    elif doc_type in ("cancelled_cheque_or_bank_letter", "bank_details_form"):
        n = _after(r"NAME\s*\(?\s*AS\s*IN\s*BANK\s*A\s*/?\s*C\s*\)?", t) or _after(r"ACCOUNT\s*HOLDER(?:\s*NAME)?", t)
        if not n:
            m = re.search(r"\bFOR\s*([A-Z][A-Za-z0-9&.,'() \-]{5,}?(?:LIMITED|LTD\.?|LLP|PVT\.? LTD\.?|ENTERPRISES|TRADERS|INDUSTRIES|COMPANY))", t, re.I)
            n = m.group(1).strip() if m else ""
        if n:
            out["account_holder"] = n
    return out


WEAK_TYPES = {"address_proof", "other_certificate", "tax_filing_document"}      # generic words that also appear as items on a form
FORM_MARKERS = re.compile(r"PART\s*[–-]\s*(I|II|III)\b|\bSL\.?\s*NO|DETAILS\s*OF|NAME\s*OF|ADDRESS|\bVALID\b|PHNO|PIN\s*CODE", re.I)


def read_page(text: str, force: list[str] | None = None) -> dict:
    """Understand one page: document types, identifiers, names, contact details, and what is still missing.
    `force` supplies the types when the caller knows better (a continuation page of a multi-page form)."""
    text = text or ""
    types = force or classify(text)
    ids = identifiers(text)
    fields: list[dict] = []
    missing: list[str] = []

    def add(field: str, value: str, dt: str):
        if value and not any(f["field"] == field and f["doc_type"] == dt and f["value"] == value for f in fields):
            fields.append({"field": field, "value": value, "doc_type": dt, "snippet": _snippet(text, value)})

    for dt in types or ["other"]:
        if dt == "other":
            continue
        for k in ("gstin", "pan", "cin"):
            if dt in ("gst_certificate", "pan_card", "incorporation_or_name_change_certificate", "vendor_registration_form", "stock_exchange_filing",
                      "udyam_certificate", "tax_filing_document", "other_certificate", "address_proof") or k == "gstin":
                for val in ids[k][:2 if dt == "vendor_registration_form" else 1]:
                    add(k, val, dt)
        if dt in ("cancelled_cheque_or_bank_letter", "bank_details_form", "vendor_registration_form"):
            for val in ids["bank_account"][:1]:
                add("bank_account", val, dt)
            for val in ids["ifsc"][:1]:
                add("ifsc", val, dt)
        for k, val in names(text, dt).items():
            if k in ("legal_name", "account_holder", "trade_name") and (LABEL_WORD.match(val.strip()) or len(val.strip()) < 6 or val.strip().lower().startswith(("of ", "the "))):
                continue                    # a printed label, not a name (the value line was not read)
            add(k, val, dt)
        if dt in ("vendor_registration_form", "tax_form_or_vat_certificate", "bank_details_form", "cancelled_cheque_or_bank_letter"):
            for k, val in foreign_identifiers(text).items():
                if k == "tax_id" and dt in ("bank_details_form", "cancelled_cheque_or_bank_letter"):
                    continue
                add(k, val, dt)
        if dt == "udyam_certificate":
            if (m := UDYAM_RE.search(text)):
                add("udyam_number", m.group(0).upper(), dt)
            if (n := _after(r"NAME\s*OF\s*(?:THE\s*)?(?:ENTERPRISE|UNIT)", text)) and not LABEL_WORD.match(n.strip()) and len(n.strip()) >= 6:
                add("legal_name", n, dt)
        if dt == "address_proof" and not any(f["field"] == "address" and f["doc_type"] == dt for f in fields) and (m := PIN_RE.search(text)):
            add("address", _norm(text)[max(0, m.start() - 70): m.end() + 5].replace("\n", " ").strip(), dt)
        if dt == "vendor_registration_form":
            for e in EMAIL_RE.findall(text)[:1]:
                add("contact_email", e, dt)
            for p in PHONE_RE.findall(text)[:1]:
                add("contact_phone", p, dt)
        if dt in ("incorporation_or_name_change_certificate", "stock_exchange_filing"):
            m = re.search(r"FORMERLY\s*KNOWN\s*AS\s+([A-Z][A-Za-z0-9&.,'() \-]{3,}?(?:LIMITED|LTD\.?))", text, re.I)
            if m:
                add("previous_name", m.group(1).strip(), dt)
                head = re.search(r"([A-Z][A-Z0-9&.,'() \-]{3,}?(?:LIMITED|LTD\.?))\s*\(\s*FORMERLY", text, re.I)
                if head:
                    add("new_name", head.group(1).strip(), dt)
        for need in NEEDS.get(dt, []):
            if not any(f["field"] == need and f["doc_type"] == dt for f in fields):
                missing.append(f"{dt}:{need}")
    return {"types": types, "fields": fields, "missing": missing, "ids": ids, "country_hints": country_hints(text),
            "undecided": (not types and len(text.strip()) > 80)}


def _snippet(text: str, value: str) -> str:
    i = text.upper().find(value.upper()[:12])
    return _norm(text[max(0, i - 30): i + len(value) + 30]).replace("\n", " ").strip()[:120] if i >= 0 else ""


def critical_from_text(text: str) -> dict[str, str]:
    """The five critical identifiers on a page, for the second (independent) read."""
    ids = identifiers(text)
    return {"gstin": (ids["gstin"] or [""])[0], "pan": (ids["pan"] or [""])[0], "cin": (ids["cin"] or [""])[0],
            "bank_account": (ids["bank_account"] or [""])[0], "ifsc": (ids["ifsc"] or [""])[0]}
