"""Cases, immutable versions, tasks and the two-person rule (R22).

Guardrails encoded here: nobody approves their own resolution; there is no urgency override."""
import secrets
from datetime import date

from sqlmodel import Session, select

from . import pipeline
from . import validators as v
from .models import Case, Evidence, Run, StageEvent, Task, Version, utcnow
from .storage import audit

USERS = {
    "priya": {"key": "priya", "name": "Priya", "role": "procurement", "title": "Procurement"},
    "arjun": {"key": "arjun", "name": "Arjun", "role": "finance", "title": "Finance"},
    "neha": {"key": "neha", "name": "Neha", "role": "finance_approver", "title": "Finance approver"},
}
CRITICAL_FIELDS = {"gstin", "pan", "cin", "bank_account", "ifsc"}
SECRET_FIELDS = {"bank_account", "bank_account_confirm"}


class WorkflowError(Exception):
    pass


def mask_if_id(field: str, value: str) -> str:
    return v.mask(value) if field in CRITICAL_FIELDS | SECRET_FIELDS else value


# ---------- cases and versions ----------

def create_case(ctx, typed: dict, files: list[dict], actor: str = "Priya", created_by: str = "staff") -> tuple[int, int]:
    typed = {k: (val.strip() if isinstance(val, str) else val) for k, val in typed.items() if val not in (None, "")}
    for k in ("gstin", "pan", "cin", "ifsc", "udyam_number"):
        if k in typed:
            typed[k] = v.clean_udyam(typed[k]) if k == "udyam_number" else v.clean(typed[k])
    with Session(ctx.engine, expire_on_commit=False) as s:
        name = typed.get("legal_name") or (files[0]["name"] if files else "New submission")
        case = Case(token=secrets.token_urlsafe(10), display_name=name, sim=ctx.sim)
        s.add(case)
        s.commit()
        s.refresh(case)
        ver = Version(case_id=case.id, number=1, created_by=created_by, declared=typed, files=files,
                      changes=[{"field": "(first submission)", "old": "", "new": f"{len(typed)} typed fields, {len(files)} file(s)"}])
        s.add(ver)
        s.commit()
        s.refresh(ver)
        audit(s, case.id, actor, "submission", f"Version 1 created with {len(typed)} typed fields and {len(files)} file(s)")
        return case.id, ver.id


def latest_version(s: Session, case_id: int) -> Version:
    return s.exec(select(Version).where(Version.case_id == case_id).order_by(Version.number.desc())).first()


def latest_run(s: Session, case_id: int) -> Run | None:
    return s.exec(select(Run).where(Run.case_id == case_id).order_by(Run.id.desc())).first()


def new_version(ctx, case_id: int, updates: dict, files: list[dict], created_by: str = "vendor", actor: str = "Vendor") -> int:
    """A correction never edits history: it opens version N+1 holding only what changed (plus carried-over values)."""
    with Session(ctx.engine, expire_on_commit=False) as s:
        case = s.get(Case, case_id)
        prev = latest_version(s, case_id)
        declared = dict(prev.declared)
        changes = []
        for k, val in updates.items():
            val = val.strip() if isinstance(val, str) else val
            if val in (None, ""):
                continue
            if k in ("gstin", "pan", "cin", "ifsc", "udyam_number"):
                val = v.clean_udyam(val) if k == "udyam_number" else v.clean(val)
            if declared.get(k) != val:
                changes.append({"field": k, "old": mask_if_id(k, str(declared.get(k, "") or "")), "new": mask_if_id(k, str(val))})
            declared[k] = val
        if created_by == "vendor":
            declared["_confirmed"] = sorted(set(declared.get("_confirmed", [])) | {k for k, val in updates.items() if val and k in CRITICAL_FIELDS})
        # files that were flagged unusable (R04) in the last run are replaced by the new uploads
        run = latest_run(s, case_id)
        drop = set()
        if run:
            read = s.exec(select(StageEvent).where(StageEvent.run_id == run.id, StageEvent.key == "read")).first()
            drop = {c["key"].split(":")[1] for c in (read.checks if read else []) if c["rule"] == "R04" and c["result"] == "flag"} if files else set()
        kept = [f for f in prev.files if f["sha256"][:8] not in drop]
        have = {f["sha256"] for f in kept}
        added = [f for f in files if f["sha256"] not in have]
        for f in prev.files:
            if f["sha256"][:8] in drop:
                changes.append({"field": "file removed", "old": f["name"], "new": ""})
        for f in added:
            changes.append({"field": "file added", "old": "", "new": f["name"]})
        ver = Version(case_id=case_id, number=prev.number + 1, created_by=created_by, declared=declared, files=kept + added, changes=changes)
        s.add(ver)
        for t in s.exec(select(Task).where(Task.case_id == case_id, Task.version_id == prev.id)).all():
            if t.status in ("open", "resolved"):
                t.status = "superseded"
                s.add(t)
        case.current_version, case.updated_at = ver.number, utcnow()
        if case.status == "rejected":      # a new application after a reapply-able rejection
            case.decided_at = None
        s.add(case)
        s.commit()
        s.refresh(ver)
        audit(s, case_id, actor, "new version", f"Version {ver.number}: " + ("; ".join(f"{c['field']}" for c in changes) or "no field changes"))
        return ver.id


# ---------- permissions ----------

def user_of(key: str) -> dict:
    return USERS.get(key, USERS["priya"])


def can_resolve(user: dict, t: Task) -> bool:
    if t.status != "open" or t.kind == "vendor":
        return False
    if t.kind == "retry" or t.owner == "system":
        return True
    return (t.owner == "procurement" and user["role"] == "procurement") or (t.owner == "finance" and user["role"] == "finance")


def can_approve(user: dict, t: Task) -> bool:
    """R22: only the finance approver, and never the person who resolved it."""
    return t.status == "resolved" and user["role"] == "finance_approver" and t.resolved_by != user["name"]


# ---------- task actions ----------

def resolve_task(ctx, task_id: int, user_key: str, outcome: str, method: str, note: str) -> None:
    user = user_of(user_key)
    with Session(ctx.engine) as s:
        t = s.get(Task, task_id)
        if not t or not can_resolve(user, t):
            raise WorkflowError(f"{user['name']} cannot resolve this item.")
        if outcome not in ("confirmed", "reject"):
            raise WorkflowError("Choose an outcome.")
        t.status, t.outcome, t.method, t.note = "resolved", outcome, method, note.strip()
        t.resolved_by, t.resolved_at = user["name"], utcnow()
        s.add(t)
        s.commit()
        audit(s, t.case_id, user["name"], "resolved", f"{t.title}: {outcome}" + (f" via {method}" if method else "") + (f" — “{note.strip()}”" if note.strip() else "")
              + " (awaiting second approval)")
        case_id = t.case_id
    pipeline.redecide(ctx, case_id)


def approve_task(ctx, task_id: int, user_key: str, approve: bool = True, background: bool = True) -> None:
    user = user_of(user_key)
    rerun = None
    with Session(ctx.engine) as s:
        t = s.get(Task, task_id)
        if not t:
            raise WorkflowError("No such item.")
        if t.resolved_by == user["name"]:
            raise WorkflowError("Nobody can approve their own resolution. A different person must approve.")
        if not can_approve(user, t):
            raise WorkflowError(f"{user['name']} cannot approve this item (only the finance approver can).")
        if approve:
            t.status, t.approved_by, t.approved_at = "approved", user["name"], utcnow()
        else:
            t.status, t.approved_by, t.approved_at = "open", "", None
            t.outcome, t.method, t.note, t.resolved_by = "", "", "", ""
        s.add(t)
        s.commit()
        audit(s, t.case_id, user["name"], "approved" if approve else "sent back", f"{t.title} (resolved by {t.resolved_by or 'n/a'})")
        case_id = t.case_id
        if approve and t.kind == "evidence":
            # assisted evidence only counts once a second person approved it; then re-run so every check sees it
            for e in s.exec(select(Evidence).where(Evidence.case_id == case_id, Evidence.mode == "assisted", Evidence.approved_by == "")).all():
                e.approved_by = user["name"]
                s.add(e)
            s.commit()
            rerun = latest_version(s, case_id).id
    if rerun:
        pipeline.start_run(ctx, case_id, rerun, trigger="assisted evidence approved", background=background)
    else:
        pipeline.redecide(ctx, case_id)


def retry_case(ctx, case_id: int, user_key: str, background: bool = True) -> int:
    user = user_of(user_key)
    with Session(ctx.engine) as s:
        ver_id = latest_version(s, case_id).id
        audit(s, case_id, user["name"], "retry", "Re-ran all checks (cached responses are reused)")
    return pipeline.start_run(ctx, case_id, ver_id, trigger=f"retry by {user['name']}", background=background)


# ---------- assisted evidence ----------

def save_assisted(ctx, case_id: int, source: str, identifier: str, fields: dict, screenshot: dict, user_key: str) -> int:
    """The reviewer checked the official site themselves and confirmed the extracted fields. Stored as mode `assisted`
    with the screenshot, reviewer and time; counts only after a second person approves (R22)."""
    user = user_of(user_key)
    with Session(ctx.engine) as s:
        ver = latest_version(s, case_id)
        s.add(Evidence(case_id=case_id, version_id=ver.id, field=f"assisted.{source}", value=identifier, source=f"Official site ({source}), reviewer-checked",
                       mode="assisted", ref=f"screenshot {screenshot['name']} ({screenshot['sha256'][:12]})", side="government",
                       meta={"identifier": identifier, "fields": fields, "screenshot": screenshot["sha256"], "screenshot_name": screenshot["name"]},
                       captured_by=user["name"]))
        key = {"gst": "R11", "pan": "R14", "udyam": "R17", "mca": "assist:mca", "taxid": "R23v"}[source]
        t = s.exec(select(Task).where(Task.case_id == case_id, Task.version_id == ver.id, Task.key == key, Task.status.in_(["open", "resolved"]))).first()
        if not t:
            t = Task(case_id=case_id, version_id=ver.id, key=f"assist:{source}", rule_id={"gst": "R11", "pan": "R14", "udyam": "R17", "mca": "R15", "taxid": "R23"}[source],
                     owner="procurement", kind="evidence", title=f"approve the {source.upper()} evidence")
        t.kind, t.status, t.outcome, t.method = "evidence", "resolved", "confirmed", "assisted official-site check"
        t.resolved_by, t.resolved_at = user["name"], utcnow()
        t.note = f"{identifier} checked on the official site; screenshot {screenshot['name']}"
        s.add(t)
        s.commit()
        audit(s, case_id, user["name"], "assisted evidence", f"{source.upper()} {v.mask(identifier)} saved with screenshot {screenshot['sha256'][:12]} (awaiting second approval)")
        return t.id


def current_fy(today: date | None = None) -> str:
    t = today or date.today()
    y = t.year if t.month >= 4 else t.year - 1
    return f"{y}-{(y + 1) % 100:02d}"


def fetch_filing_history(ctx, case_id: int, user_key: str, today: date | None = None, background: bool = True) -> str:
    """R13 on demand (one credit). Returns '' on success or a plain-language problem."""
    user = user_of(user_key)
    today = today or date.today()
    with Session(ctx.engine) as s:
        ver = latest_version(s, case_id)
        gstin = v.clean(ver.profile.get("values", {}).get("gstin") or ver.declared.get("gstin"))
    if not gstin:
        return "No GSTIN on this case yet."
    fy = current_fy(today)
    res = ctx.gst.returns(gstin, fy)
    if not res.ok:
        return res.message or "Filing history is unavailable right now."
    start = int(fy[:4])
    expected = [f"{start}-{m:02d}" for m in range(4, 13)] + [f"{start + 1}-{m:02d}" for m in range(1, 4)]
    cutoff = f"{today.year}-{today.month:02d}"
    expected = [p for p in expected if p < cutoff]
    missing = [p for p in expected if p not in set(res.fields["gstr3b_periods"])]
    with Session(ctx.engine) as s:
        s.add(Evidence(case_id=case_id, version_id=ver.id, field="assisted.filings", value=f"{len(missing)} missing", source=res.source, mode=res.mode,
                       ref=res.ref, side="government", captured_by=user["name"], approved_by="system",
                       meta={"identifier": gstin, "fy": fy, "missing_periods": missing, "filed": res.fields["gstr3b_periods"]}))
        s.commit()
        audit(s, case_id, user["name"], "filing history", f"Fetched GSTR-3B history for FY {fy}: {len(missing)} month(s) missing")
    pipeline.start_run(ctx, case_id, ver.id, trigger="filing history fetched", background=background)
    return ""


COMMERCIAL_KEYS = ("vendor_type", "expense_category", "department_owner", "negotiated_terms", "system_terms")


def set_commercial(ctx, case_id: int, user_key: str, fields: dict, background: bool = True) -> int:
    """Procurement categorises the vendor and sets the payment terms. Like every change this opens a new immutable version."""
    user = user_of(user_key)
    if user["role"] != "procurement":
        raise WorkflowError("Only procurement categorises vendors and sets payment terms.")
    updates = {k: (fields.get(k) or "").strip() for k in COMMERCIAL_KEYS if (fields.get(k) or "").strip()}
    vid = new_version(ctx, case_id, updates, [], created_by="staff", actor=user["name"])
    return pipeline.start_run(ctx, case_id, vid, trigger="categorisation / payment terms", background=background)


def verify_pan_live(ctx, case_id: int, user_key: str, background: bool = True) -> str:
    """PAN verify through the GST API (4-6 credits): on demand only. Returns '' on success or a plain-language problem."""
    user = user_of(user_key)
    with Session(ctx.engine) as s:
        ver = latest_version(s, case_id)
        vals = ver.profile.get("values", {})
        pan = v.clean(vals.get("pan") or ver.declared.get("pan") or ver.profile.get("derived_pan"))
        name = vals.get("legal_name") or ver.declared.get("legal_name")
    if not v.check_pan(pan).ok:
        return "There is no valid PAN on this case to verify."
    res = ctx.gst.pan_verify(pan, name)
    if not res.ok:
        return res.message or "PAN verification is unavailable right now."
    with Session(ctx.engine) as s:
        s.add(Evidence(case_id=case_id, version_id=ver.id, field="assisted.pan_api", value=res.fields.get("name", ""), source=res.source, mode=res.mode, ref=res.ref,
                       side="government", captured_by=user["name"], approved_by="system",
                       meta={"identifier": pan, "fields": res.fields, "fetched_at": res.fetched_at, "from_cache": res.from_cache}))
        s.commit()
        audit(s, case_id, user["name"], "PAN verify", f"Live PAN verification via the GST API ({'cached' if res.from_cache else 'about 5 credits'})")
    pipeline.start_run(ctx, case_id, ver.id, trigger="PAN verified live", background=background)
    return ""
