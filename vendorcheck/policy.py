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
}


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
    new["blocklist"] = {"pans": [p for p in dict.fromkeys(pans) if _PAN.match(p)], "accounts": [a for a in dict.fromkeys(accounts) if re.fullmatch(r"\d{6,20}", a)]}
    return new, errors


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
