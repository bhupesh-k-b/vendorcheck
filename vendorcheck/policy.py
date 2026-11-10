"""Loads policy.yaml. The engine reads thresholds and accepted evidence modes from here."""
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import yaml

from . import config

DEFAULTS = {
    "name_match_threshold": 92,
    "read_confidence": 80,                      # % : numbers read from a scan or photo below this are not trusted; the vendor is asked to confirm them
    "rename_requires_person": False,
    "requirements": {
        "gst_registration": ["live", "assisted"],
        "pan_identity": ["live", "assisted", "derived_from_gst"],
        "bank_account": ["live", "assisted"],
        "company_status": ["live", "assisted", "document"],
        "udyam": ["live", "assisted"],
        "tax_registration": ["live", "assisted"],
    },
    "recheck_days": {"company_status": 30, "advisory": 90},
    "reverify_days": 365,
    "msme_payment_terms_days": 45,
    "filing_gap_months": 2,
    "require_documents": "if_uploaded",        # always | if_uploaded | off: when the required-documents checklist blocks
    "require_commercial_setup": True,           # R27/R28: categorisation and payment terms must be set before approval
    "blocklist": {"pans": [], "accounts": []},
    # Compliance documents: which built-in documents the checklist asks for (a switched-off one is not asked for), plus documents you add yourself.
    "documents": {"enabled": {}, "custom": []},
    # Identity details: which built-in details are collected and checked, plus details you add yourself (format-checked).
    "details": {"enabled": {}, "custom": []},
}

# built-in identity details: key -> (label, what switching it off does, the form fields it covers)
DETAIL_KEYS = {
    "gstin": ("GSTIN", "Off: no GSTIN field, format check or GST registry lookup", ["gstin"]),
    "pan": ("PAN", "Off: no PAN field or PAN checks (the PAN inside a GSTIN is still read from it)", ["pan"]),
    "cin": ("CIN", "Off: no CIN field, company-status check or CIN document comparison", ["cin"]),
    "bank": ("Bank account and IFSC", "Off: no bank details are collected or checked, and Finance is not asked to confirm an account",
             ["bank_account", "bank_account_confirm", "ifsc", "account_holder", "iban", "swift", "routing_code"]),
}
# quick-add templates for details you add: key -> (label, format, applies to, hint)
DETAIL_PRESETS = {
    "tan": ("TAN", "AAAA99999A", "india", "Tax Deduction Account Number, for example PNEK12345E"),
    "fssai": ("FSSAI licence number", "99999999999999", "india", "14 digits"),
    "iec": ("Import Export Code (IEC)", "**********", "all", "10 letters or digits"),
    "duns": ("D-U-N-S number", "999999999", "all", "9 digits"),
    "lei": ("Legal Entity Identifier (LEI)", "********************", "all", "20 letters or digits"),
}


def detail_on(policy: dict, key: str) -> bool:
    return bool(((policy.get("details") or {}).get("enabled") or {}).get(key, True))


def disabled_fields(policy: dict) -> set[str]:
    """Form and document fields that are switched off: the run behaves as if the vendor never supplied them."""
    return {f for k, (_, _, fields) in DETAIL_KEYS.items() if not detail_on(policy, k) for f in fields}


def custom_details(policy: dict) -> list[dict]:
    """Details you added: [{key, label, format, required, applies}]. The typed value is stored under x_<key>."""
    return [d for d in ((policy.get("details") or {}).get("custom") or []) if d.get("enabled", True)]


def applies_to(d: dict, country: str) -> bool:
    c = (country or "").upper()
    return d.get("applies", "all") == "all" or (d["applies"] == "india" and c == "IN") or (d["applies"] == "foreign" and bool(c) and c != "IN")


def format_regex(fmt: str):
    """A simple format to a regex: A = a letter, 9 = a digit, * = a letter or digit, anything else is literal. Spaces and dashes are ignored on both sides."""
    out = []
    for ch in re.sub(r"[\s\-]", "", fmt.upper()):
        out.append({"A": "[A-Z]", "9": r"\d", "*": "[A-Z0-9]"}.get(ch, re.escape(ch)))
    return re.compile("".join(out))


def format_ok(fmt: str, value: str) -> bool:
    return bool(format_regex(fmt).fullmatch(re.sub(r"[\s\-]", "", (value or "").upper())))


def details_from_form(form, errors: list[str], current: dict | None = None) -> dict:
    """The identity-details section of the Settings form."""
    if form.get("details_form") != "1":
        return deepcopy(current) if current else {"enabled": {}, "custom": []}
    enabled = {k: form.get(f"detail__{k}") == "on" for k in DETAIL_KEYS}
    labels, formats, required, applies = (_getlist(form, f"cdetail_{x}") for x in ("label", "format", "required", "applies"))
    taken = {"legal_name", "gstin", "pan", "cin", "tax_id", "bank_account", "ifsc", "iban", "swift", "country", "account_holder", "routing_code"}
    custom: list[dict] = []
    for i, label in enumerate(labels):
        label = label.strip()[:60]
        if not label:
            continue
        fmt = (formats[i] if i < len(formats) else "").strip().upper()[:40]
        if not re.sub(r"[\s\-]", "", fmt) or not re.search(r"[A9*]", fmt):
            errors.append(f"{label}: give a format using A (letter), 9 (digit) or * (letter or digit), for example AAAA99999A. Left out.")
            continue
        if len(custom) >= MAX_CUSTOM_DOCS:
            errors.append(f"At most {MAX_CUSTOM_DOCS} extra details. {label} left out.")
            continue
        key = _slug(label, taken)
        taken.add(key)
        custom.append({"key": key, "label": label, "format": fmt, "required": (required[i] if i < len(required) else "yes") == "yes",
                       "applies": applies[i] if i < len(applies) and applies[i] in APPLIES else "all"})
    return {"enabled": enabled, "custom": custom}

# built-in checklist documents: key -> (label, when it applies)
BUILTIN_DOCS = {
    "pan_card": ("PAN card", "Every Indian vendor"),
    "gst_certificate": ("GST registration certificate", "When a GSTIN is given"),
    "bank_document": ("Cancelled cheque or bank letter", "Every vendor"),
    "address_proof": ("Address proof", "When a GSTIN is given"),
    "udyam_certificate": ("Udyam certificate (MSME)", "When MSME status is claimed. Switching it off also skips every MSME check"),
    "incorporation": ("Certificate of incorporation", "Companies and LLPs"),
    "tax_form": ("Tax registration document", "Vendors outside India"),
}
# quick-add templates for custom documents: key -> (label, keywords that appear on the document, applies to)
DOC_PRESETS = {
    "aadhaar_card": ("Aadhaar card", ["AADHAAR", "UNIQUE IDENTIFICATION AUTHORITY"], "india"),
    "iso_certificate": ("ISO certificate", ["ISO 9001", "ISO 14001", "ISO 27001", "ISO 45001"], "all"),
    "fssai_licence": ("FSSAI licence", ["FSSAI", "FOOD SAFETY AND STANDARDS AUTHORITY"], "india"),
    "shop_establishment": ("Shop and Establishment licence", ["SHOPS AND ESTABLISHMENT", "SHOP & ESTABLISHMENT"], "india"),
    "iec": ("Import Export Code (IEC)", ["IMPORTER EXPORTER CODE", "IMPORT EXPORT CODE", "DGFT"], "all"),
    "trade_licence": ("Trade licence", ["TRADE LICENCE", "TRADE LICENSE"], "all"),
}
APPLIES = {"all": "Every vendor", "india": "Indian vendors", "foreign": "Vendors outside India"}
MAX_CUSTOM_DOCS = 12


def doc_enabled(policy: dict, key: str) -> bool:
    return bool(((policy.get("documents") or {}).get("enabled") or {}).get(key, True))


def custom_docs(policy: dict) -> list[dict]:
    """The documents you added: [{key, label, keywords, need, applies}]."""
    return [d for d in ((policy.get("documents") or {}).get("custom") or []) if d.get("enabled", True)]


def load_policy(path: Path | None = None) -> dict:
    data = deepcopy(DEFAULTS)
    p = path or config.POLICY_PATH
    if p.exists():
        loaded = yaml.safe_load(p.read_text()) or {}
        for k, v in loaded.items():
            if isinstance(v, dict) and isinstance(data.get(k), dict):
                data[k].update(v)
            else:
                data[k] = v
    return data


# ---------- editing from the Settings page ----------

# approval requirement -> (label, what it covers, evidence kinds the policy may accept for it)
REQUIREMENTS = {
    "gst_registration": ("GST registration", "The GSTIN is active", ["live", "assisted"]),
    "pan_identity": ("PAN identity", "The PAN exists and belongs to the vendor", ["live", "assisted", "derived_from_gst"]),
    "bank_account": ("Bank account", "The account is active and held by the vendor", ["live", "assisted"]),
    "company_status": ("Company status", "The company is active (CIN)", ["live", "assisted", "document"]),
    "udyam": ("Udyam (MSME)", "The MSME registration is genuine", ["live", "assisted"]),
    "tax_registration": ("Tax registration, outside India", "A person checked the official register", ["live", "assisted"]),
}
EVIDENCE_LABEL = {"live": "Live registry", "assisted": "Manual check, second person approves", "document": "Uploaded document",
                  "derived_from_gst": "Taken from the GST record"}
DOCUMENT_MODES = {"always": "Always", "if_uploaded": "When a document pack is uploaded", "off": "Never block"}
_PAN = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")


def _int(form, key, lo, hi, label, errors, default):
    raw = str(form.get(key, "")).strip()
    try:
        n = int(raw)
    except ValueError:
        errors.append(f"{label} must be a whole number.")
        return default
    if not lo <= n <= hi:
        errors.append(f"{label} must be between {lo} and {hi}.")
        return default
    return n


def policy_from_form(form, current: dict) -> tuple[dict, list[str]]:
    """Build a policy from the Settings form. Anything invalid keeps its current value and is reported."""
    errors: list[str] = []
    new = deepcopy(current)
    new["name_match_threshold"] = _int(form, "name_match_threshold", 50, 100, "Name match threshold", errors, current["name_match_threshold"])
    new["read_confidence"] = _int(form, "read_confidence", 50, 100, "Reading confidence", errors, current["read_confidence"])
    new["rename_requires_person"] = form.get("rename_requires_person") == "on"
    mode = form.get("require_documents", current["require_documents"])
    new["require_documents"] = mode if mode in DOCUMENT_MODES else current["require_documents"]
    new["require_commercial_setup"] = form.get("require_commercial_setup") == "on"
    new["msme_payment_terms_days"] = _int(form, "msme_payment_terms_days", 1, 365, "MSME payment terms", errors, current["msme_payment_terms_days"])
    new["filing_gap_months"] = _int(form, "filing_gap_months", 0, 12, "Filing gap", errors, current["filing_gap_months"])
    new["reverify_days"] = _int(form, "reverify_days", 30, 3650, "Re-verification period", errors, current["reverify_days"])
    new["recheck_days"] = {"company_status": _int(form, "recheck_company_status", 1, 365, "Company status re-check", errors, current["recheck_days"]["company_status"]),
                           "advisory": _int(form, "recheck_advisory", 1, 365, "Advisory re-check", errors, current["recheck_days"]["advisory"])}
    reqs = {}
    for key, (label, _, allowed) in REQUIREMENTS.items():
        picked = [m for m in allowed if form.get(f"req__{key}__{m}") == "on"]
        if not picked:
            errors.append(f"{label}: accept at least one kind of evidence.")
            picked = list(current["requirements"].get(key, allowed))
        reqs[key] = picked
    new["requirements"] = reqs
    pans = [x.strip().upper() for x in re.split(r"[\s,;]+", str(form.get("blocklist_pans", ""))) if x.strip()]
    accounts = [re.sub(r"\s", "", x) for x in re.split(r"[\n,;]+", str(form.get("blocklist_accounts", ""))) if x.strip()]
    bad = [p for p in pans if not _PAN.match(p)] + [a for a in accounts if not re.fullmatch(r"\d{6,20}", a)]
    if bad:
        errors.append("Blocklist entries not recognised and left out: " + ", ".join(bad[:5]) + ("…" if len(bad) > 5 else "") + ".")
    new["documents"] = documents_from_form(form, errors, current.get("documents"))
    new["details"] = details_from_form(form, errors, current.get("details"))
    if form.get("items_form") == "1":                                # the unified extra-items list replaces both older lists
        docs_c, dets_c = items_from_form(form, errors)
        new["documents"]["custom"], new["details"]["custom"] = docs_c, dets_c
    new["blocklist"] = {"pans": [p for p in dict.fromkeys(pans) if _PAN.match(p)], "accounts": [a for a in dict.fromkeys(accounts) if re.fullmatch(r"\d{6,20}", a)]}
    return new, errors


# quick-add templates for extra compliance items: key -> (label, number format or "", words on its document, applies to)
ITEM_PRESETS = {
    "fssai": ("FSSAI licence", "99999999999999", ["FSSAI", "FOOD SAFETY AND STANDARDS AUTHORITY"], "india"),
    "tan": ("TAN", "AAAA99999A", ["TAX DEDUCTION ACCOUNT NUMBER", "TAN ALLOTMENT"], "india"),
    "aadhaar": ("Aadhaar card", "", ["AADHAAR", "UNIQUE IDENTIFICATION AUTHORITY"], "india"),
    "iso": ("ISO certificate", "", ["ISO 9001", "ISO 14001", "ISO 27001", "ISO 45001"], "all"),
    "iec": ("Import Export Code (IEC)", "**********", ["IMPORTER EXPORTER CODE", "IMPORT EXPORT CODE", "DGFT"], "all"),
    "shop": ("Shop and Establishment licence", "", ["SHOPS AND ESTABLISHMENT", "SHOP & ESTABLISHMENT"], "india"),
    "trade": ("Trade licence", "", ["TRADE LICENCE", "TRADE LICENSE"], "all"),
    "duns": ("D-U-N-S number", "999999999", [], "all"),
    "lei": ("Legal Entity Identifier (LEI)", "********************", [], "all"),
}


def items_for_ui(policy: dict) -> list[dict]:
    """Every extra item (enabled or not) as one row: name, number format, words on its document, required, applies, on/off. Documents and details with the same key are one item."""
    docs = {d["key"]: d for d in ((policy.get("documents") or {}).get("custom") or [])}
    dets = {d["key"]: d for d in ((policy.get("details") or {}).get("custom") or [])}
    out = []
    for key in [*docs, *[k for k in dets if k not in docs]]:
        d, t = docs.get(key), dets.get(key)
        out.append({"label": (d or t).get("item") or (d or t)["label"], "format": (t or {}).get("format", ""), "words": ", ".join((d or {}).get("keywords", [])),
                    "need": (d or {}).get("need", 1), "required": "yes" if (d or t).get("required", True) else "no", "applies": (d or t).get("applies", "all"),
                    "enabled": bool((d or t).get("enabled", True))})
    return out


def items_from_form(form, errors: list[str]) -> tuple[list[dict], list[dict]]:
    """The extra compliance items on the Settings form. Each can have a number (format) and/or a document (words); returns (documents, details)."""
    cols = {x: _getlist(form, f"item_{x}") for x in ("label", "format", "words", "need", "required", "applies", "enabled")}
    taken = set(BUILTIN_DOCS) | {"legal_name", "gstin", "pan", "cin", "tax_id", "bank_account", "ifsc", "iban", "swift", "country", "account_holder", "routing_code",
                                 "other", "vendor_registration_form", "stock_exchange_filing", "tax_filing_document", "other_certificate", "bank_details_form"}
    docs, dets = [], []

    def col(name, i, default=""):
        return cols[name][i] if i < len(cols[name]) else default
    for i, label in enumerate(cols["label"]):
        label = label.strip()[:60]
        if not label:
            continue
        fmt = col("format", i).strip().upper()[:40]
        if fmt and not (re.sub(r"[\s\-]", "", fmt) and re.search(r"[A9*]", fmt)):
            errors.append(f"{label}: the number format needs A (letter), 9 (digit) or * (letter or digit), for example AAAA99999A. The number was left out.")
            fmt = ""
        kws = [w.strip().upper() for w in re.split(r"[,\n]+", col("words", i)) if w.strip()][:12]
        if not fmt and not kws:
            errors.append(f"{label}: give a number format, words that appear on its document, or both. Left out.")
            continue
        if len(docs) + len(dets) >= 2 * MAX_CUSTOM_DOCS:
            errors.append(f"At most {MAX_CUSTOM_DOCS} extra items. {label} left out.")
            continue
        key = _slug(label, taken)
        taken.add(key)
        scope = col("applies", i, "all")
        scope = scope if scope in APPLIES else "all"
        required = col("required", i, "yes") == "yes"
        enabled = col("enabled", i, "on") != "off"
        try:
            need = max(1, min(int(col("need", i, "1") or 1), len(kws) or 1, 5))
        except ValueError:
            need = 1
        if kws:
            docs.append({"key": key, "label": label, "keywords": kws, "need": need, "applies": scope, "required": required, "enabled": enabled})
        if fmt:
            dets.append({"key": key, "label": f"{label} number" if kws else label, "item": label, "format": fmt, "required": required, "applies": scope, "enabled": enabled})
    return docs, dets


def _getlist(form, key: str) -> list[str]:
    if hasattr(form, "getlist"):
        return [str(x) for x in form.getlist(key)]
    val = form.get(key, [])
    return [str(x) for x in (val if isinstance(val, list) else [val])]


def _slug(label: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "document"
    key, n = base, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    return key


def documents_from_form(form, errors: list[str], current: dict | None = None) -> dict:
    """The compliance-document section of the Settings form: one switch per built-in document, and any number of documents you added."""
    if form.get("docs_form") != "1":                      # this section was not on the submitted form: keep what is set
        return deepcopy(current) if current else {"enabled": {}, "custom": []}
    enabled = {k: form.get(f"doc__{k}") == "on" for k in BUILTIN_DOCS}
    labels, words, needs, applies = (_getlist(form, f"custom_{x}") for x in ("label", "keywords", "need", "applies"))
    taken = set(BUILTIN_DOCS) | {"other", "vendor_registration_form", "stock_exchange_filing", "tax_filing_document", "other_certificate", "bank_details_form"}
    custom: list[dict] = []
    for i, label in enumerate(labels):
        label = label.strip()[:60]
        if not label:
            continue
        kws = [w.strip().upper() for w in re.split(r"[,\n]+", words[i] if i < len(words) else "") if w.strip()]
        if not kws:
            errors.append(f"{label}: add at least one word that appears on the document. Left out.")
            continue
        if len(custom) >= MAX_CUSTOM_DOCS:
            errors.append(f"At most {MAX_CUSTOM_DOCS} extra documents. {label} left out.")
            continue
        try:
            need = max(1, min(int(needs[i]) if i < len(needs) else 1, len(kws), 5))
        except ValueError:
            need = 1
        scope = applies[i] if i < len(applies) and applies[i] in APPLIES else "all"
        key = _slug(label, taken)
        taken.add(key)
        custom.append({"key": key, "label": label, "keywords": kws[:12], "need": need, "applies": scope})
    return {"enabled": enabled, "custom": custom}


def save_policy(policy: dict, path: Path | None = None) -> None:
    keep = {k: v for k, v in policy.items() if k in DEFAULTS}
    (path or config.POLICY_PATH).write_text("# VendorCheck policy. Edited from Settings; every change applies to the next verification run.\n"
                                            + yaml.safe_dump(keep, sort_keys=False, default_flow_style=False))


def simulation_policy(policy: dict) -> dict:
    """Test-bench only: also accept `recorded` evidence so recorded scenarios can reach a result.
    Real runs never use this; a run made with it is labelled 'Simulated' everywhere."""
    sim = deepcopy(policy)
    for req, modes in sim["requirements"].items():
        if "recorded" not in modes:
            modes.append("recorded")
    sim["simulation"] = True
    return sim


@lru_cache
def cached_policy() -> dict:
    return load_policy()
