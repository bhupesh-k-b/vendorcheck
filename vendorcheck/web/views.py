"""View-model builders: turn database rows into the plain dicts the templates render."""
import re
import statistics
from datetime import datetime, timezone

from markupsafe import Markup, escape
from sqlmodel import Session, select

from .. import countries as cn
from .. import validators as v
from ..models import Audit, Case, Evidence, Run, StageEvent, Task, VendorMaster, Version, utcnow
from ..workflow import can_approve, can_resolve, latest_run, latest_version

STAGE_ORDER = ["intake", "read", "validate", "verify", "reconcile", "decide", "communicate"]
STAGE_BLURB = {
    "intake": "Store the files, open a version, look for an existing vendor",
    "read": "Read every page, identify each document and extract its details",
    "validate": "Format and checksum checks on every identifier, no external calls",
    "verify": "Confirm identifiers with the official registries",
    "reconcile": "Compare typed, document and registry values",
    "decide": "Apply the approval rules and reach a decision",
    "communicate": "Prepare the vendor message, open tasks and audit trail",
}

_ID_PATTERNS = [
    re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z][A-Z0-9][A-Z0-9]\b"),     # GSTIN
    re.compile(r"\b[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b"),                  # CIN
    re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"),                                 # IFSC (shown in full; not secret)
    re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),                                   # PAN
    re.compile(r"\b\d{9,18}\b"),                                             # account number
]


def mask_ids(text) -> Markup:
    """Mask identifiers to their last four characters by default. A top-bar toggle reveals them."""
    s = str(escape(text if text is not None else ""))
    for i, pat in enumerate(_ID_PATTERNS):
        if i == 2:    # IFSC identifies a bank branch, not an account: leave readable
            continue
        s = pat.sub(lambda m: f'<span class="idv"><span class="idm">{v.mask(m.group())}</span><span class="idf">{m.group()}</span></span>', s)
    return Markup(s)


def ist(dt: datetime | None, fmt: str = "%d %b, %H:%M") -> str:
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(__import__("datetime").timedelta(hours=5, minutes=30))).strftime(fmt)


def dur(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 1:
        return f"{int(seconds * 1000)} ms"
    if seconds < 90:
        return f"{seconds:.1f} s"
    if seconds < 3600 * 2:
        return f"{int(seconds // 60)} min"
    if seconds < 86400 * 2:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} d"


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def seconds_between(a, b) -> float | None:
    a, b = _aware(a), _aware(b)
    return (b - a).total_seconds() if a and b else None


# ---------- dashboard ----------

def case_rows(s: Session, status: str = "", waiting: str = "", q: str = "", sim: bool | None = None) -> list[dict]:
    """Every case, newest first. sim=None lists real and simulated cases together (simulated ones carry a tag); True/False lists only those."""
    rows = []
    query = select(Case).order_by(Case.updated_at.desc())
    if sim is not None:
        query = query.where(Case.sim == sim)
    for c in s.exec(query).all():
        ver = latest_version(s, c.id)
        run = latest_run(s, c.id)
        vals = {**(ver.declared if ver else {}), **(ver.profile.get("values", {}) if ver else {})}
        gstin = vals.get("gstin") or vals.get("tax_id") or ""
        r = {"case": c, "gstin": gstin, "country": (vals.get("country") or "").upper(), "versions": c.current_version, "run": run,
             "runs": len(s.exec(select(Run.id).where(Run.case_id == c.id)).all()),
             "docs": len(ver.files) if ver else 0, "form": form_state(ver.declared) if ver else None,
             "missing_items": [i["label"] + ("" if i.get("doc") == "missing" or i.get("number") in ("missing", "bad") else " (" + " and ".join(x for x, k in (("name", "name_check"), ("address", "address_check")) if i.get(k) == "differs") + " differs)")
                               for i in (ver.profile.get("compliance", []) if ver else [])
                               if i.get("doc") == "missing" or i.get("number") in ("missing", "bad") or i.get("name_check") == "differs" or i.get("address_check") == "differs"],
             "tta": seconds_between(c.created_at, c.decided_at) if c.decided_at else None}
        if status and c.status != status:
            continue
        if waiting and c.waiting_on != waiting:
            continue
        if q and q.lower() not in (c.display_name + gstin + c.vendor_code).lower():
            continue
        rows.append(r)
    return rows


def kpis(s: Session) -> dict:
    cases = list(s.exec(select(Case)).all())
    pend = [c for c in cases if c.status == "pending"]
    ttd = [seconds_between(c.created_at, c.decided_at) for c in cases if c.decided_at]
    return {"total": len(cases), "approved": sum(c.status == "approved" for c in cases), "rejected": sum(c.status == "rejected" for c in cases),
            "running": sum(c.status == "running" for c in cases), "pending": len(pend),
            "pending_by": {o: sum(c.waiting_on == o for c in pend) for o in ("vendor", "procurement", "finance", "system")},
            "median_ttd": statistics.median(ttd) if ttd else None}


# ---------- run view ----------

def email_draft(case: Case, values: dict, decision: dict, matrix: dict | None) -> dict:
    """A ready-to-send email listing everything missing or inconsistent. Vendor-facing, so identifiers inside it are
    already masked to their last four characters by the message templates."""
    lines: list[str] = []
    for it in (decision or {}).get("message", {}).get("items", []):
        lines.append(it["text"])
    for r in (matrix or {}).get("rows", []):
        if r["kind"] == "typed":
            continue
        for f, c in r["cells"].items():
            if c["state"] == "missing":
                label = dict((matrix or {}).get("fields", [])).get(f, f)
                lines.append(f"{r['label']} ({r['ref']}) does not show the {label if label.isupper() or label.split()[0].isupper() else label.lower()}. Please send a document that shows it.")
            elif c["state"] == "unclear":
                label = dict((matrix or {}).get("fields", [])).get(f, f)
                lines.append(f"The {label if label.isupper() or label.split()[0].isupper() else label.lower()} on {r['label']} ({r['ref']}) is not clear. Please send a sharper copy.")
    seen, uniq = set(), []
    for ln in lines:
        if ln not in seen:
            seen.add(ln)
            uniq.append(ln)
    greeting = f"Dear {values.get('contact_name') or case.display_name},"
    if uniq:
        body = (greeting + "\n\nThank you for your vendor registration. Before we can finish onboarding, we need the following:\n\n"
                + "\n".join(f"{i}. {t}" for i, t in enumerate(uniq, 1))
                + "\n\nYou can send only these items; everything else you submitted stays as it is. You can also correct them on your secure page: {LINK}\n\nThank you,\nProcurement team")
    else:
        body = greeting + "\n\nThank you for your vendor registration. We have everything we need from you for now.\n\nThank you,\nProcurement team"
    return {"to": values.get("contact_email", ""), "subject": f"Action needed on your vendor registration: {case.display_name}" if uniq else f"Your vendor registration: {case.display_name}",
            "body": body, "count": len(uniq), "token": case.token}


def verify_links(values: dict, stages: list[dict], case_id: int = 0) -> list[dict]:
    """'Check it yourself' rows: each identifier, the official page, and what our checks found."""
    by = {c["key"]: c for s in stages for c in s["checks"]}

    def status(key: str, ok_text: str = "") -> tuple[str, str]:
        c = by.get(key)
        if not c:
            return "none", "Not checked yet"
        if c["result"] == "pass":
            return "ok", ok_text or c.get("found") or "Checked"
        if c["result"] == "note":
            return "ok", c.get("found") or "Checked"
        if c["result"] in ("flag", "reject"):
            return "bad", c.get("found") or c.get("reason", "")
        return "none", "Not checked: " + (c.get("reason") or "waiting")
    out = []
    country = (values.get("country") or "IN").upper()
    if country != "IN":
        tid = values.get("tax_id")
        if tid:
            c = by.get("R23v")
            tone = {"pass": "ok", "note": "ok", "flag": "bad", "reject": "bad"}.get(c["result"], "none") if c else "none"
            site = cn.SITES.get(country, ("The tax authority's online register", ""))
            out.append({"label": "Tax ID", "ident": tid, "tone": tone,
                        "status": (c.get("found") or "Confirmed by a person on the official register") if tone != "none" else "Format checked only: nobody has confirmed it exists yet",
                        "url": site[1] or "https://www.google.com/search?q=" + cn.name_of(country).replace(" ", "+") + "+tax+id+verification", "site": site[0], "copy": True, "action": ""})
        return out
    g, p, cin, ifsc, ud = (values.get(k) for k in ("gstin", "pan", "cin", "ifsc", "udyam_number"))
    if g:
        tone, text = status("R11")
        r11 = by.get("R11")
        out.append({"label": "GSTIN", "ident": g, "tone": tone, "status": (r11["found"] + " · " + (r11["mode"] or "")) if r11 and r11["result"] in ("pass", "reject", "flag") else text,
                    "url": "https://services.gst.gov.in/services/searchtp", "site": "GST portal: Search Taxpayer (Active / Suspended / Cancelled)", "copy": True})
    if p:
        tone, text = status("R14")
        out.append({"label": "PAN", "ident": p, "tone": tone if tone == "ok" else "none",
                    "status": "Taken from the active GST registration; not checked on the Income Tax site" if tone == "ok" else "Not verified: check it on the Income Tax site",
                    "url": "https://eportal.incometax.gov.in/iec/foservices/#/pre-login/verifyYourPAN", "site": "Income Tax e-filing: Verify Your PAN", "copy": True,
                    "action": f"/cases/{case_id}/verify-pan" if (by.get("R14") or {}).get("mode") != "live" else ""})
    if cin:
        c = by.get("R15")
        out.append({"label": "CIN", "ident": cin, "tone": "none", "status": ((c or {}).get("found") or "Company status not verified") if c else "Not checked",
                    "url": "https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html", "site": "MCA master data (may need a free login)", "copy": True})
    if ifsc:
        tone, text = status("R09")
        out.append({"label": "IFSC", "ident": ifsc, "tone": tone, "status": text, "url": f"https://ifsc.razorpay.com/{ifsc}", "site": "Bank and branch details (RBI list)", "copy": False})
    if ud:
        tone, text = status("R17")
        out.append({"label": "Udyam", "ident": ud, "tone": tone, "status": text, "url": "https://udyamregistration.gov.in/Udyam_Verify.aspx", "site": "Udyam registration: Verify", "copy": True})
    return out


def form_state(declared: dict) -> dict | None:
    """Was the typed form filled in? None = yes. {'state': 'empty'} = nothing typed; {'state': 'partial', 'missing': [...]} = key details left out."""
    def has(*keys):
        return any(str((declared or {}).get(k) or "").strip() for k in keys)
    if not has("legal_name", "gstin", "pan", "cin", "tax_id", "bank_account", "iban", "ifsc"):
        return {"state": "empty", "missing": []}
    missing = []
    if not has("legal_name"):
        missing.append("Legal name")
    if not has("gstin", "pan", "tax_id"):
        missing.append("Tax ID")
    if not has("bank_account", "iban"):
        missing.append("Bank account")
    return {"state": "partial", "missing": missing} if missing else None


def _duplicates(stages: list[dict]) -> dict | None:
    """What the intake duplicate search found (evaluated before any record was created), for the 'Existing vendor found' card."""
    intake = next((s_ for s_ in stages if s_["key"] == "intake"), None)
    c = next((c_ for c_ in (intake["checks"] if intake else []) if c_.get("rule") == "I2"), None)
    if not c or not c.get("found") or c["found"].startswith("No existing"):
        return None
    hits = re.findall(r"(PAN|GSTIN|bank account) → (VND-\d+) \(([^)]*)\)", c["found"])
    if not hits:
        return None
    codes = sorted({code for _, code, _ in hits})
    by_code = {code: {"code": code, "name": next(n for _, cd, n in hits if cd == code), "keys": [k for k, cd, _ in hits if cd == code]} for code in codes}
    return {"vendors": list(by_code.values()), "conflict": len(codes) > 1}


def run_view(s: Session, run_id: int, user: dict) -> dict | None:
    run = s.get(Run, run_id)
    if not run:
        return None
    case = s.get(Case, run.case_id)
    ver = s.get(Version, run.version_id)
    events = {e.key: e for e in s.exec(select(StageEvent).where(StageEvent.run_id == run_id)).all()}
    now = utcnow()
    stages, first_blocking = [], None
    running = run.status == "running"
    for key in STAGE_ORDER:
        e = events[key]
        elapsed = None
        if e.status == "running" and e.started_at:
            elapsed = seconds_between(e.started_at, now)
        d = seconds_between(e.started_at, e.ended_at) if e.ended_at else None
        checks = e.checks or []
        for c in checks:
            if not first_blocking and (c["result"] in ("flag", "wait", "reject")):
                first_blocking = c["key"] + "@" + key
                c["_first"] = True
        stages.append({"key": key, "name": e.name, "status": e.status, "summary": e.summary, "blurb": STAGE_BLURB[key], "elapsed": elapsed, "dur": d, "checks": checks})
    latest = latest_run(s, case.id)
    is_latest = latest and latest.id == run.id
    decision = case.decision if (is_latest and not running) else {}
    tasks = list(s.exec(select(Task).where(Task.case_id == case.id, Task.version_id == ver.id).order_by(Task.id)).all()) if is_latest else []
    items = []
    for it in decision.get("open_items", []):
        t = next((t for t in tasks if t.key == it["key"] and t.status != "superseded"), None)
        items.append({**it, "task": t, "can_resolve": bool(t and can_resolve(user, t)), "can_approve": bool(t and can_approve(user, t))})
    return {"dup": _duplicates(stages), "form_state": form_state(ver.declared), "run": run, "case": case, "version": ver, "stages": stages, "running": running, "is_latest": bool(is_latest), "decision": decision, "items": items,
            "tasks": tasks, "table": ver.profile.get("table", []), "matrix": ver.profile.get("matrix") or None,
            "links": verify_links({**ver.declared, **ver.profile.get("values", {})}, stages, case.id),
            "doc_map": ver.profile.get("doc_map", []), "files": ver.files, "checklist": ver.profile.get("checklist", []), "compliance": ver.profile.get("compliance", []),
            "n_open": sum(1 for s_ in stages for c_ in s_["checks"] if c_["result"] in ("flag", "wait", "reject")),
            "pv": {**ver.declared, **ver.profile.get("values", {})},
            "country": (ver.profile.get("values", {}).get("country") or ver.declared.get("country") or "").upper(),
            "country_name": cn.name_of((ver.profile.get("values", {}).get("country") or ver.declared.get("country") or "").upper()) if (ver.profile.get("values", {}).get("country") or ver.declared.get("country")) else "unknown",
            "country_inferred": not ver.declared.get("country"),
            "email": email_draft(case, {**ver.declared, **ver.profile.get("values", {})}, decision, ver.profile.get("matrix")) if (decision and not running) else None, "first_blocking": first_blocking, "total_dur": seconds_between(run.started_at, run.finished_at or now),
            "message": decision.get("message") if decision else None, "status": case.status if is_latest else "earlier",
            "evidence": s.exec(select(Evidence).where(Evidence.run_id == run.id)).all()}


# ---------- case page ----------

def case_view(s: Session, case_id: int) -> dict:
    case = s.get(Case, case_id)
    versions = list(s.exec(select(Version).where(Version.case_id == case_id).order_by(Version.number)).all())
    runs = list(s.exec(select(Run).where(Run.case_id == case_id).order_by(Run.id)).all())
    audit = list(s.exec(select(Audit).where(Audit.case_id == case_id).order_by(Audit.id)).all())
    ev = list(s.exec(select(Evidence).where(Evidence.case_id == case_id).order_by(Evidence.id)).all())
    master = s.exec(select(VendorMaster).where(VendorMaster.vendor_code == case.vendor_code)).first() if case.vendor_code else None
    by_version = {}
    for r in runs:
        by_version.setdefault(r.version_id, []).append(r)
    return {"case": case, "versions": versions, "runs": runs, "audit": audit, "evidence": ev, "master": master, "runs_by_version": by_version,
            "latest_run": runs[-1] if runs else None}
