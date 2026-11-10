"""The seven-stage run. Every stage persists a stage event (start, end, one-line summary, its checks), so a
page refresh or a server restart never loses a run: unfinished runs are resumed at startup."""
import threading
import time
import traceback
from datetime import date

from sqlmodel import Session, select

from . import master as vm
from .policy import disabled_fields
from . import messages
from . import stages as S
from .decide import decide
from .models import Case, Evidence, Run, StageEvent, Task, Version, utcnow
from .rules import FLAG, INFO, PASS, REJECT, WAIT, Check
from .storage import audit

STAGES = [("intake", "Intake"), ("read", "Read"), ("validate", "Validate"), ("verify", "Verify"), ("reconcile", "Reconcile"),
          ("decide", "Decide"), ("communicate", "Communicate & record")]
CHECK_STAGES = ["intake", "read", "validate", "verify", "reconcile"]
FUNCS = {"intake": S.stage_intake, "read": S.stage_read, "validate": S.stage_validate, "verify": S.stage_verify, "reconcile": S.stage_reconcile}


# ---------- run creation ----------

def create_run(ctx, case_id: int, version_id: int, trigger: str = "submission") -> int:
    with Session(ctx.engine, expire_on_commit=False) as s:
        n = len(s.exec(select(Run).where(Run.case_id == case_id)).all()) + 1
        run = Run(case_id=case_id, version_id=version_id, number=n, trigger=trigger, sim=ctx.sim)
        s.add(run)
        s.commit()
        s.refresh(run)
        for i, (k, name) in enumerate(STAGES, 1):
            s.add(StageEvent(run_id=run.id, idx=i, key=k, name=name))
        case = s.get(Case, case_id)
        case.status, case.waiting_on, case.reason, case.updated_at = "running", "", "Checks are running", utcnow()
        s.add(case)
        s.commit()
        audit(s, case_id, "system", "run started", f"Run {n} ({trigger}) on version {s.get(Version, version_id).number}")
        return run.id


def start_run(ctx, case_id: int, version_id: int, trigger: str = "submission", background: bool = True) -> int:
    run_id = create_run(ctx, case_id, version_id, trigger)
    if background:
        threading.Thread(target=execute_run, args=(ctx, run_id), daemon=True, name=f"run-{run_id}").start()
    else:
        execute_run(ctx, run_id)
    return run_id


def recover_runs(ctx) -> list[int]:
    """Restart safety: runs left 'running' are re-run from the start; caches make that nearly free."""
    with Session(ctx.engine) as s:
        ids = [r.id for r in s.exec(select(Run).where(Run.status == "running")).all()]
        for rid in ids:
            for ev in s.exec(select(StageEvent).where(StageEvent.run_id == rid)).all():
                ev.status, ev.started_at, ev.ended_at, ev.summary, ev.checks = "queued", None, None, "", []
                s.add(ev)
        s.commit()
    for rid in ids:
        threading.Thread(target=execute_run, args=(ctx, rid), daemon=True, name=f"resume-{rid}").start()
    return ids


# ---------- state ----------

def load_assisted(s: Session, case_id: int) -> dict:
    out: dict[str, list] = {}
    for e in s.exec(select(Evidence).where(Evidence.case_id == case_id, Evidence.mode == "assisted")).all():
        if e.field.startswith("assisted.") and e.approved_by:
            out.setdefault(e.field.split(".", 1)[1], []).append({"meta": e.meta, "captured_by": e.captured_by, "approved_by": e.approved_by})
    # filing history captured live on demand is stored the same way but with mode "live"
    for fld, key in (("assisted.filings", "filings"), ("assisted.pan_api", "pan_api")):
        for e in s.exec(select(Evidence).where(Evidence.case_id == case_id, Evidence.field == fld)).all():
            out.setdefault(key, []).append({"meta": e.meta, "captured_by": e.captured_by, "approved_by": e.approved_by})
    return out


def load_state(ctx, run_id: int) -> S.RunState:
    with Session(ctx.engine, expire_on_commit=False) as s:
        run = s.get(Run, run_id)
        case, version = s.get(Case, run.case_id), s.get(Version, run.version_id)
        return S.RunState(case=case, version=version, run=run, files=list(version.files), typed={k: val for k, val in version.declared.items() if k not in disabled_fields(ctx.policy)},   # details switched off in Settings are ignored
                          assisted=load_assisted(s, case.id))


def _set_stage(ctx, run_id: int, idx: int, **kw) -> None:
    with Session(ctx.engine) as s:
        ev = s.exec(select(StageEvent).where(StageEvent.run_id == run_id, StageEvent.idx == idx)).one()
        for k, v in kw.items():
            setattr(ev, k, v)
        s.add(ev)
        s.commit()


def _stage_status(checks: list[Check]) -> str:
    return "flagged" if any(c.blocking or c.result == REJECT for c in checks) else "passed"


# ---------- execution ----------

def execute_run(ctx, run_id: int) -> None:
    st = load_state(ctx, run_id)
    cursor = 0
    failed = False
    try:
        for idx, (key, name) in enumerate(STAGES, 1):
            st.cur = key
            _set_stage(ctx, run_id, idx, status="running", started_at=utcnow(), summary="", checks=[])
            st.progress = lambda msg, _i=idx: _set_stage(ctx, run_id, _i, summary=msg)
            t0 = time.monotonic()
            err = None
            try:
                if key == "decide":
                    summary, status = do_decide(ctx, st)
                elif key == "communicate":
                    summary, status = do_communicate(ctx, st)
                else:
                    summary = FUNCS[key](ctx, st)
                    status = _stage_status(st.checks.get(key, []))
            except Exception as e:   # noqa: BLE001  a bug must show up as a failed stage, never a silent hang
                traceback.print_exc()
                err = e
                summary, status = f"Internal error: {e}", "failed"
                st.add(Check("SYS", WAIT, name="Internal error", owner="system", kind="retry", title="investigate the internal error",
                             reason=f"Stage '{name}' failed: {e}", found=type(e).__name__))
            hold = ctx.pacing - (time.monotonic() - t0)
            if hold > 0:
                time.sleep(hold)
            _persist_evidence(ctx, st, cursor)
            cursor = len(st.evidence)
            _save_profile(ctx, st)
            _set_stage(ctx, run_id, idx, status=status, ended_at=utcnow(), summary=summary,
                       checks=[c.to_dict() for c in st.checks.get(key, [])])
            if err:
                failed = True
                break
    finally:
        with Session(ctx.engine) as s:
            run = s.get(Run, run_id)
            run.status, run.finished_at = ("error" if failed else "done"), utcnow()
            s.add(run)
            if failed:
                case = s.get(Case, run.case_id)
                case.status, case.waiting_on, case.reason = "pending", "system", "Pending: waiting on the system (an internal error stopped the run)"
                s.add(case)
            s.commit()


def _persist_evidence(ctx, st: S.RunState, cursor: int) -> None:
    with Session(ctx.engine) as s:
        for e in st.evidence[cursor:]:
            s.add(Evidence(case_id=st.case.id, version_id=st.version.id, run_id=st.run.id, **e))
        s.commit()


def _save_profile(ctx, st: S.RunState) -> None:
    with Session(ctx.engine) as s:
        ver = s.get(Version, st.version.id)
        ver.profile = {"values": {k: v for k, v in st.profile.items() if v not in (None, "")}, "unconfirmed": st.unconfirmed, "prov": st.prov,
                       "table": st.table, "matrix": st.matrix, "doc_map": st.doc_map, "checklist": st.checklist, "derived_pan": st.derived_pan, "renames": st.renames}
        s.add(ver)
        s.commit()


# ---------- tasks ----------

def _tasks(s: Session, case_id: int, version_id: int | None = None) -> list[Task]:
    q = select(Task).where(Task.case_id == case_id)
    if version_id:
        q = q.where(Task.version_id == version_id)
    return list(s.exec(q.order_by(Task.id)).all())


def task_dict(t: Task) -> dict:
    return {"id": t.id, "key": t.key, "status": t.status, "outcome": t.outcome, "resolved_by": t.resolved_by, "approved_by": t.approved_by,
            "method": t.method, "note": t.note, "kind": t.kind}


def sync_tasks(s: Session, case_id: int, version_id: int, open_items: list[dict]) -> None:
    existing = _tasks(s, case_id, version_id)
    keys = {it["key"] for it in open_items}
    have = {t.key for t in existing if t.status != "superseded"}
    for it in open_items:
        if it["key"] not in have:
            s.add(Task(case_id=case_id, version_id=version_id, key=it["key"], rule_id=it["rule"], owner=it["owner"], kind=it["kind"],
                       title=it["title"], detail=it["detail"] or it["reason"], payload={"assist": it.get("assist", ""), "reason": it["reason"]}))
    for t in existing:
        if t.key not in keys and t.status in ("open", "resolved") and not t.key.startswith("assist:"):
            t.status = "superseded"
            s.add(t)
    s.commit()


# ---------- stage 6: Decide ----------

def _all_checks(ctx, st: S.RunState) -> list[dict]:
    return [c.to_dict() for k in CHECK_STAGES for c in st.checks.get(k, [])]


def do_decide(ctx, st: S.RunState) -> tuple[str, str]:
    checks = _all_checks(ctx, st)
    with Session(ctx.engine, expire_on_commit=False) as s:
        tasks = [task_dict(t) for t in _tasks(s, st.case.id, st.version.id)]
        decision = decide(checks, tasks, ctx.policy, date.today())
        sync_tasks(s, st.case.id, st.version.id, decision["open_items"])
        # attach task ids to open items
        by_key = {t.key: t.id for t in _tasks(s, st.case.id, st.version.id) if t.status != "superseded"}
        for it in decision["open_items"]:
            it["task_id"] = by_key.get(it["key"])
        case = s.get(Case, st.case.id)
        if st.master:
            case.update_of = st.master.vendor_code
        if case.display_name in ("", "New submission") or case.display_name.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".heic")):
            case.display_name = st.profile.get("legal_name") or case.display_name
        case.status, case.waiting_on, case.reason = decision["status"], decision["waiting_on"], decision["reason"]
        case.explanation = " ".join(e["text"] for e in decision["explanations"] if e["rule"] == "R12")
        case.decision = {**decision, "version": st.version.number, "simulated": bool(ctx.sim or ctx.policy.get("simulation"))}
        case.updated_at = utcnow()
        if decision["status"] in ("approved", "rejected") and not case.decided_at:
            case.decided_at = utcnow()
        s.add(case)
        s.commit()
        audit(s, case.id, "system", "decision", f"{decision['status']}: {decision['reason']}")
    st.decision = decision
    st.all_checks = checks
    gate = ("Rejected" if decision["status"] == "rejected" else "Pending" if decision["status"] == "pending" else "Approved")
    st.add(Check("D1", INFO, name=f"Gate result: {gate}", found=decision["reason"], mode="computed", source="Decide (rules + policy.yaml)",
                 reason="Rejected if any reject outcome; Pending if any blocking check is open; otherwise Approved. The model never decides."))
    status = {"approved": "passed", "pending": "flagged", "rejected": "failed"}[decision["status"]]
    return decision["reason"], status


# ---------- stage 7: Communicate and record ----------

def do_communicate(ctx, st: S.RunState) -> tuple[str, str]:
    decision, checks = st.decision, st.all_checks
    with Session(ctx.engine, expire_on_commit=False) as s:
        case = s.get(Case, st.case.id)
        ver = s.get(Version, st.version.id)
        msg = messages.compose(case.display_name, ver.number, decision, checks)
        parts = [f"vendor message ready ({len(msg['items'])} item{'s' if len(msg['items']) != 1 else ''})"]
        code = case.vendor_code
        if decision["status"] == "approved" and not ctx.sim:
            code = _commit_master(ctx, s, case, ver, checks, decision)
            case.vendor_code = code
            parts.append(f"vendor master {code} saved")
        elif decision["status"] == "approved":
            parts.append("simulation: vendor master NOT written")
        case.decision = {**case.decision, "message": msg}
        s.add(case)
        s.commit()
        owners = decision.get("owners", {})
        if owners:
            parts.append("tasks: " + ", ".join(f"{n} for {o}" for o, n in owners.items()))
            audit(s, case.id, "system", "tasks", ", ".join(f"{it['title']} → {it['owner']}" for it in decision["open_items"]))
    return " · ".join(parts), "passed" if decision["status"] != "rejected" else "flagged"


def _commit_master(ctx, s: Session, case: Case, ver: Version, checks: list[dict], decision: dict) -> str:
    by_key = {c["key"]: c for c in checks}
    tasks = {t.key: t for t in _tasks(s, case.id, ver.id) if t.status == "approved" and t.outcome == "confirmed" and t.approved_by != t.resolved_by}
    bank = None
    r16 = by_key.get("R16")
    if r16 and r16["result"] == PASS and r16.get("meta", {}).get("bank_confirmation"):
        bank = {k: v for k, v in r16["meta"]["bank_confirmation"].items() if k != "carried"} | {"verified_via": r16["meta"]["bank_confirmation"].get("verified_via", "")}
    for key in ("R18", "R16"):
        if key in tasks:
            t = tasks[key]
            bank = {"verified_via": "finance confirmation", "method": t.method, "verified_by": t.resolved_by, "approved_by": t.approved_by, "mode": "assisted"}
    profile = {**ver.profile.get("values", {})}
    m = vm.commit_approved(s, case, profile, checks, decision, bank, ctx.policy, ctx.policy["reverify_days"])
    audit(s, case.id, "system", "vendor master", f"{m.vendor_code} {'updated' if case.update_of else 'created'}")
    return m.vendor_code


# ---------- re-decide after a human action (no new run needed) ----------

def redecide(ctx, case_id: int) -> None:
    """Recompute stages 6-7 from the latest run's stored checks after a task is approved. Cheap and pure."""
    with Session(ctx.engine, expire_on_commit=False) as s:
        case = s.get(Case, case_id)
        run = s.exec(select(Run).where(Run.case_id == case_id).order_by(Run.id.desc())).first()
        if not run:
            return
        events = {e.key: e for e in s.exec(select(StageEvent).where(StageEvent.run_id == run.id)).all()}
        st = load_state(ctx, run.id)
        st.master = s.exec(select(vm.VendorMaster).where(vm.VendorMaster.vendor_code == case.update_of)).first() if case.update_of else None
        for k in CHECK_STAGES:
            st.checks[k] = [Check(**{f: c[f] for f in Check.__dataclass_fields__ if f in c}) for c in events[k].checks]
        st.profile = dict(st.version.profile.get("values", {}))
    for key, fn in (("decide", do_decide), ("communicate", do_communicate)):
        st.cur = key
        summary, status = fn(ctx, st)
        with Session(ctx.engine) as s:
            ev = s.exec(select(StageEvent).where(StageEvent.run_id == run.id, StageEvent.key == key)).one()
            ev.summary, ev.status, ev.ended_at = summary, status, utcnow()
            ev.checks = [c.to_dict() for c in st.checks.get(key, [])]
            s.add(ev)
            s.commit()
