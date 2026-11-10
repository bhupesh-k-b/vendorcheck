"""The vendor message: built from failed checks with templates, never free-form AI text.

Plain language, identifiers already masked to their last four characters, one consolidated message per
version. Never reveals internal fraud signals (R02, R18, R19) or another vendor's data."""


def vendor_status_sentence(status: str, waiting_on: str, rejected: dict | None) -> str:
    if status == "approved":
        return "You are approved as a vendor. Thank you."
    if status == "rejected":
        if rejected and rejected.get("reapply"):
            return "We could not approve this application with the GSTIN given, but you can apply again with an active GSTIN."
        return "We are unable to onboard you with these details. Please contact the procurement team."
    if status == "running":
        return "We are checking your details right now."
    if waiting_on == "vendor":
        return "We need a few things from you before we can finish onboarding."
    return "Thank you. Your details are with our team for checks; nothing more is needed from you right now."


def compose(display_name: str, version_no: int, decision: dict, checks: list[dict]) -> dict:
    """Return the consolidated vendor message for one version."""
    items = []
    seen = set()
    for it in decision.get("open_items", []):
        if it["owner"] == "vendor" and it.get("vendor_text"):
            items.append(it)
    rej = decision.get("rejected")
    if rej and rej.get("reapply"):
        c = next((c for c in checks if c["key"] == rej.get("key")), None)
        if c and c.get("vendor_text"):
            items.append({"vendor_text": c["vendor_text"], "vendor_fields": c.get("vendor_fields", []), "vendor_upload": False, "key": c["key"]})
    numbered, fields, upload = [], [], False
    for it in items:
        if it["vendor_text"] in seen:
            continue
        seen.add(it["vendor_text"])
        numbered.append({"n": len(numbered) + 1, "text": it["vendor_text"], "fields": it.get("vendor_fields", []), "upload": it.get("vendor_upload", False),
                         "key": it["key"]})
        for f in it.get("vendor_fields", []):
            if f not in fields:
                fields.append(f)
        upload = upload or it.get("vendor_upload", False)
    status = decision["status"]
    intro = vendor_status_sentence(status, decision.get("waiting_on", ""), rej)
    return {"to": display_name, "version": version_no, "subject": f"Your vendor registration — version {version_no}", "intro": intro,
            "items": numbered, "fields": fields, "upload": upload,
            "outro": "Reply with only the items above; you do not need to resend anything else." if numbered else ""}
