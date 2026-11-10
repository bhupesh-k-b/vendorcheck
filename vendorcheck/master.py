"""Vendor master: lookups by PAN / GSTIN / bank account, and the approved vendor record."""
from datetime import date, timedelta

from sqlmodel import Session, select

from .models import VendorMaster, utcnow
from .validators import clean, mask


def _days(text) -> int | None:
    import re
    m = re.search(r"\d+", str(text or ""))
    return int(m.group(0)) if m else None


def identity_key(profile: dict) -> str:
    """The key a vendor is known by: the PAN for Indian vendors, COUNTRY:TAXID for everyone else."""
    country = (profile.get("country") or "IN").upper()
    if country == "IN":
        return clean(profile.get("pan"))
    return f"{country}:{clean(profile.get('tax_id'))}" if profile.get("tax_id") else ""


def all_masters(s: Session) -> list[VendorMaster]:
    return list(s.exec(select(VendorMaster)).all())


def find_matches(s: Session, pan: str = "", gstin: str = "", account: str = "") -> tuple[VendorMaster | None, list[str]]:
    """Return the vendor matching by PAN or GSTIN (R01) and what it matched on."""
    pan, gstin = clean(pan), clean(gstin)
    for m in all_masters(s):
        on = []
        if pan and m.pan == pan:
            on.append("PAN")
        if gstin and any(g["gstin"] == gstin for g in m.record.get("gstins", [])):
            on.append("GSTIN")
        if on:
            return m, on
    return None, []


def search_duplicates(s: Session, pan: str = "", gstin: str = "", account: str = "") -> dict[str, VendorMaster]:
    """Search the vendor master by PAN, GSTIN and bank account BEFORE a new record is created. Returns the vendor each key matched."""
    pan, gstin = clean(pan), clean(gstin)
    acct = (account or "").replace(" ", "")
    found: dict[str, VendorMaster] = {}
    for m in all_masters(s):
        if pan and m.pan == pan:
            found.setdefault("PAN", m)
        if gstin and any(g["gstin"] == gstin for g in m.record.get("gstins", [])):
            found.setdefault("GSTIN", m)
        if acct and any(b["account"] == acct for b in m.record.get("bank_accounts", [])):
            found.setdefault("bank account", m)
    return found


def accounts_of_other_pans(s: Session, account: str, pan: str) -> list[VendorMaster]:
    """R02: vendors with a DIFFERENT PAN that already use this bank account."""
    out = []
    for m in all_masters(s):
        if m.pan != clean(pan) and any(b["account"] == account for b in m.record.get("bank_accounts", [])):
            out.append(m)
    return out


def active_bank(m: VendorMaster) -> dict | None:
    return next((b for b in m.record.get("bank_accounts", []) if b.get("status") == "active"), None)


def next_code(s: Session) -> str:
    """One above the highest code ever issued (never a count: deletions or gaps cannot cause a repeat)."""
    import re
    nums = [int(m.group(1)) for x in all_masters(s) if (m := re.fullmatch(r"VND-(\d+)", x.vendor_code))]
    return f"VND-{(max(nums) if nums else 0) + 1:04d}"


def save_unique(s: Session, m: VendorMaster) -> VendorMaster:
    """Persist a vendor record. The vendor code has a database UNIQUE constraint; if a concurrent approval took the code,
    take the next one and retry, so a duplicate code can never be saved."""
    from sqlalchemy.exc import IntegrityError
    for _ in range(8):
        try:
            s.add(m)
            s.commit()
            s.refresh(m)
            return m
        except IntegrityError:
            s.rollback()
            m.vendor_code = next_code(s)
    raise RuntimeError("could not allocate a unique vendor code")


def tds_note(pan_status: str, pan: str) -> str:
    if pan_status == "inoperative":
        return "PAN is inoperative: higher TDS applies until it is linked to Aadhaar."
    kind = {"C": "company", "P": "individual/proprietor", "F": "firm/LLP"}.get(pan[3:4], "entity")
    return f"PAN valid ({kind}): standard TDS rate for the payment type applies."


def commit_approved(s: Session, case, profile: dict, checks: list[dict], decision: dict, bank_confirmed_by: dict | None,
                    policy: dict, reverify_days: int) -> VendorMaster:
    """Create or update the vendor master record for an approved case. Bank details are applied only if the
    bank check passed (verified account carried forward, or a confirmed R16/R18 resolution)."""
    today = date.today()
    by_rule = {c["key"]: c for c in checks}
    country = (profile.get("country") or "IN").upper()
    pan = identity_key(profile)
    existing = s.exec(select(VendorMaster).where(VendorMaster.vendor_code == case.update_of)).first() if case.update_of else None
    m = existing or VendorMaster(vendor_code=next_code(s), pan=pan, case_id=case.id)
    rec = m.record or {"gstins": [], "bank_accounts": [], "evidence_modes": {}, "conditions": [], "case_ids": []}

    mode_of = lambda key: (by_rule.get(key) or {}).get("mode", "") or ""    # noqa: E731
    gst = (by_rule.get("R11") or {}).get("meta", {}).get("gst", {})
    gstin = clean(profile.get("gstin"))
    if gstin and not any(g["gstin"] == gstin for g in rec["gstins"]):
        rec["gstins"].append({"gstin": gstin, "state": gst.get("state", ""), "status": gst.get("status", ""),
                              "taxpayer_type": gst.get("taxpayer_type", ""), "einvoice": gst.get("einvoice_status", "unknown"),
                              "mode": mode_of("R11")})
    else:
        for g in rec["gstins"]:
            if g["gstin"] == gstin and gst:
                g.update({"status": gst.get("status", g["status"]), "taxpayer_type": gst.get("taxpayer_type", g["taxpayer_type"])})
    rec["legal_name"] = profile.get("legal_name", "")
    rec["trade_name"] = gst.get("trade_name") or profile.get("trade_name", "")
    rec["country"] = country
    if country == "IN":
        rec["pan"] = {"value": pan, "status": "valid", "mode": mode_of("R14") or mode_of("R08")}
    else:
        rec["tax_id"] = {"value": clean(profile.get("tax_id")), "country": country, "mode": mode_of("R23v") or "assisted",
                         "note": "format checked automatically; registration checked by a person on the official site"}
    if clean(profile.get("cin")):
        r15 = by_rule.get("R15") or {}
        rec["cin"] = {"value": clean(profile["cin"]), "company_status": r15.get("meta", {}).get("company_status", "not verified"),
                      "mode": r15.get("mode", "") or "none"}
    r17 = by_rule.get("R17") or {}
    if profile.get("msme"):
        rec["msme"] = {"udyam": profile.get("udyam_number", ""), "type": r17.get("meta", {}).get("enterprise_type", ""),
                       "payment_terms_days": r17.get("meta", {}).get("payment_terms_days"), "mode": r17.get("mode", "")}
    rec["tds_note"] = tds_note("valid", pan) if country == "IN" else "Non-Indian vendor: withholding and tax-form requirements (e.g. W-8BEN, VAT) are handled by finance outside this check."
    rec["contact"] = {"name": profile.get("contact_name", ""), "email": profile.get("contact_email", ""), "phone": profile.get("contact_phone", "")}
    if existing and rec.get("contact_on_file") is None:
        rec["contact_on_file"] = rec["contact"]
    rec.setdefault("contact_on_file", rec["contact"])

    # bank: apply the submitted account only when it is verified (carried forward, penny drop, or approved confirmation)
    acct = (profile.get("iban") or profile.get("bank_account") or "").strip()
    if acct and bank_confirmed_by:
        for b in rec["bank_accounts"]:
            if b["status"] == "active" and b["account"] != acct:
                b["status"] = "superseded"
        if not any(b["account"] == acct and b["status"] == "active" for b in rec["bank_accounts"]):
            rec["bank_accounts"].append({"account": acct, "ifsc": clean(profile.get("ifsc") or profile.get("swift")), "status": "active", **bank_confirmed_by,
                                         "at": utcnow().isoformat(timespec="seconds")})
    rec["classification"] = {"vendor_type": profile.get("vendor_type", ""), "expense_category": profile.get("expense_category", ""),
                             "department_owner": profile.get("department_owner", "")}
    rec["payment_terms"] = {"configured": profile.get("system_terms", ""), "negotiated": profile.get("negotiated_terms", ""),
                            "matches_negotiated": _days(profile.get("system_terms")) is not None and _days(profile.get("system_terms")) == _days(profile.get("negotiated_terms"))}
    rec["simulated"] = bool(getattr(case, "sim", False))
    rec["status"] = "active"
    rec["last_verified"] = today.isoformat()
    rec["next_reverify"] = (today + timedelta(days=reverify_days)).isoformat()
    rec["conditions"] = decision.get("conditions", [])
    rec["evidence_modes"] = {k: c.get("mode", "") for k, c in by_rule.items() if c.get("mode")}
    rec["case_ids"] = sorted(set(rec.get("case_ids", []) + [case.id]))
    m.record, m.legal_name, m.updated_at, m.status = rec, rec["legal_name"], utcnow(), "active"
    return save_unique(s, m)


def display_account(b: dict) -> str:
    return f"{mask(b['account'])} · {b['ifsc']}"
