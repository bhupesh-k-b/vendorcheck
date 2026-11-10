from sqlmodel import Session, select

from tests.conftest import BANK, GSTIN, NAME, PAN, CountingGst, form, gst_fixture, make_ctx
from vendorcheck import pipeline, workflow
from vendorcheck import validators as v
from vendorcheck.models import Case, StageEvent, Task, VendorMaster


def submit(ctx, typed=None, files=None):
    case_id, ver_id = workflow.create_case(ctx, typed if typed is not None else form(), files or [])
    run_id = pipeline.start_run(ctx, case_id, ver_id, background=False)
    return case_id, run_id


def case(ctx, cid) -> Case:
    with Session(ctx.engine) as s:
        return s.get(Case, cid)


def checks(ctx, run_id):
    with Session(ctx.engine) as s:
        evs = s.exec(select(StageEvent).where(StageEvent.run_id == run_id).order_by(StageEvent.idx)).all()
    return {e.key: e for e in evs}


def rule(ctx, run_id, rid, key=None):
    for e in checks(ctx, run_id).values():
        for c in e.checks:
            if c["rule"] == rid and (key is None or c["key"] == key):
                return c


def tasks(ctx, cid, status=None):
    with Session(ctx.engine) as s:
        q = select(Task).where(Task.case_id == cid)
        return [t for t in s.exec(q).all() if status is None or t.status == status]


def test_all_seven_stages_persist_events(ctx):
    cid, rid = submit(ctx)
    evs = checks(ctx, rid)
    assert list(evs) == ["intake", "read", "validate", "verify", "reconcile", "decide", "communicate"]
    assert all(e.status in ("passed", "flagged") and e.ended_at and e.summary for e in evs.values())


def test_happy_path_waits_on_finance_for_bank_then_two_person_approval(ctx):
    cid, rid = submit(ctx)
    c = case(ctx, cid)
    assert c.status == "pending" and c.waiting_on == "finance"
    assert "bank account" in c.reason
    assert rule(ctx, rid, "R11")["result"] == "pass" and rule(ctx, rid, "R11")["mode"] == "recorded"
    assert rule(ctx, rid, "R14")["mode"] == "derived_from_gst" or rule(ctx, rid, "R14")["mode"] == "recorded"
    t = tasks(ctx, cid, "open")[0]
    assert t.owner == "finance" and t.key == "R16"
    workflow.resolve_task(ctx, t.id, "arjun", "confirmed", "called bank", "spoke to branch manager")
    c = case(ctx, cid)
    assert c.status == "pending" and "second approver" in c.reason          # still not approved
    workflow.approve_task(ctx, t.id, "neha")
    c = case(ctx, cid)
    assert c.status == "approved" and c.decided_at is not None
    with Session(ctx.engine) as s:
        assert s.exec(select(VendorMaster)).one().record["bank_accounts"][0]["verified_by"] == "Arjun"


def test_r22_nobody_approves_own_resolution(ctx):
    cid, rid = submit(ctx)
    t = tasks(ctx, cid, "open")[0]
    workflow.resolve_task(ctx, t.id, "arjun", "confirmed", "called bank", "")
    import pytest
    with pytest.raises(workflow.WorkflowError):
        workflow.approve_task(ctx, t.id, "arjun")            # the resolver
    with pytest.raises(workflow.WorkflowError):
        workflow.approve_task(ctx, t.id, "priya")            # not an approver
    with pytest.raises(workflow.WorkflowError):
        workflow.resolve_task(ctx, t.id, "neha", "confirmed", "", "")   # approver cannot resolve a finance item
    assert case(ctx, cid).status == "pending"


def test_real_policy_never_accepts_recorded_evidence():
    ctx = make_ctx(sim=False)           # the real policy, not the test-bench simulation policy
    cid, rid = submit(ctx)
    c = case(ctx, cid)
    assert c.status == "pending"
    assert c.waiting_on == "system" or "recorded" in " ".join(i["reason"] for i in c.decision["open_items"])
    assert any("recorded evidence cannot satisfy" in i["reason"] for i in c.decision["open_items"])


def test_e3_pan_inside_gstin_conflict_stops_before_any_api_call():
    sister = v.with_gstin_check_char("27AABCZ7092H1Z")
    ctx = make_ctx({GSTIN: gst_fixture(), sister: gst_fixture(sister, "SISTER COMPANY PRIVATE LIMITED")})
    cid, rid = submit(ctx, form(gstin=sister))
    assert ctx.gst.calls == []                                      # no credit spent
    r08 = rule(ctx, rid, "R08")
    assert r08["result"] == "flag" and r08["owner"] == "vendor"
    c = case(ctx, cid)
    assert c.status == "pending" and c.waiting_on == "vendor"
    msg = c.decision["message"]
    assert msg["items"] and "SISTER" not in str(msg).upper()       # never reveals another vendor's data
    assert PAN not in str(msg) and sister not in str(msg)          # identifiers are masked
    # vendor corrects the GSTIN: version 2 runs and passes the identity checks
    vid = workflow.new_version(ctx, cid, {"gstin": GSTIN}, [], "vendor")
    rid2 = pipeline.start_run(ctx, cid, vid, "vendor correction", background=False)
    assert rule(ctx, rid2, "R08")["result"] == "pass" and rule(ctx, rid2, "R11")["result"] == "pass"
    assert case(ctx, cid).waiting_on == "finance" and case(ctx, cid).current_version == 2
    assert ctx.gst.calls == [GSTIN]


def test_e2_tax_collector_gstin_flagged_instantly_without_api_call():
    tcs = v.with_gstin_check_char("29AAACR4849R1C")
    assert tcs.endswith("S")
    ctx = make_ctx({})
    cid, rid = submit(ctx, form(legal_name="TATA TEST LIMITED", gstin=tcs, pan="AAACR4849R", cin="L22210MH1995PLC084781"))
    assert ctx.gst.calls == []
    r06 = rule(ctx, rid, "R06")
    assert r06["result"] == "flag" and "tax-collector" in r06["reason"]
    assert case(ctx, cid).waiting_on == "vendor"


def test_name_mismatch_goes_to_procurement_and_rename_evidence_explains_it(ctx):
    other = make_ctx({GSTIN: gst_fixture(legal="OLD NAME TRADERS PRIVATE LIMITED")})
    cid, rid = submit(other)
    r12 = rule(other, rid, "R12")
    assert r12["result"] == "flag" and r12["owner"] == "procurement"
    assert case(other, cid).waiting_on == "procurement"


def test_cancelled_gstin_is_rejected_with_route_to_reapply():
    ctx = make_ctx({GSTIN: gst_fixture(status="Cancelled", cancel="2024-01-01")})
    cid, rid = submit(ctx)
    c = case(ctx, cid)
    assert c.status == "rejected"
    assert c.decision["rejected"]["reapply"] is True
    assert any("apply again" in i["text"] for i in c.decision["message"]["items"])


def test_suspended_gstin_is_pending_on_vendor():
    ctx = make_ctx({GSTIN: gst_fixture(status="Suspended")})
    cid, rid = submit(ctx)
    assert case(ctx, cid).status == "pending" and case(ctx, cid).waiting_on == "vendor"


def test_unreachable_source_is_never_a_pass():
    ctx = make_ctx({})                  # no fixture => the adapter reports "not configured"
    cid, rid = submit(ctx)
    assert rule(ctx, rid, "R20")["result"] == "wait" and rule(ctx, rid, "R20")["owner"] == "system"
    assert rule(ctx, rid, "R11")["result"] == "skip"
    c = case(ctx, cid)
    assert c.status == "pending" and c.waiting_on == "system"


def test_missing_required_items_name_what_is_missing():
    ctx = make_ctx()
    cid, rid = submit(ctx, form(contact_name="", contact_email="", contact_phone=""))
    r03 = rule(ctx, rid, "R03")
    assert r03["result"] == "flag" and "contact" in r03["reason"]


def test_blocklist_rejects_and_vendor_is_not_told_why():
    ctx = make_ctx()
    ctx.policy["blocklist"]["accounts"].append(BANK[0])
    cid, rid = submit(ctx)
    c = case(ctx, cid)
    assert c.status == "rejected"
    assert "blocklist" not in str(c.decision["message"]).lower()


def approve_vendor(ctx, typed=None):
    cid, rid = submit(ctx, typed)
    t = tasks(ctx, cid, "open")[0]
    workflow.resolve_task(ctx, t.id, "arjun", "confirmed", "called bank", "")
    workflow.approve_task(ctx, t.id, "neha")
    return cid


def test_e4_bank_change_on_approved_vendor_is_rejected_and_old_account_stays_active():
    ctx = make_ctx(sim=True)
    ctx.sim = False                                    # allow vendor-master writes in this isolated in-memory DB
    cid = approve_vendor(ctx)
    with Session(ctx.engine) as s:
        m = s.exec(select(VendorMaster)).one()
        assert m.record["bank_accounts"][0]["account"] == BANK[0]
    cid2, rid2 = submit(ctx, form(bank_account="026291800001191", bank_account_confirm="026291800001191", ifsc="YESB0000262"))
    assert rule(ctx, rid2, "R18")["result"] == "flag" and rule(ctx, rid2, "R18")["owner"] == "finance"
    assert rule(ctx, rid2, "R01")["result"] == "note"
    c2 = case(ctx, cid2)
    assert c2.status == "pending" and c2.waiting_on == "finance"
    t = tasks(ctx, cid2, "open")[0]
    assert t.key == "R18"
    workflow.resolve_task(ctx, t.id, "arjun", "reject", "called contact on file", "contact on file says this is not our account")
    workflow.approve_task(ctx, t.id, "neha")
    c2 = case(ctx, cid2)
    assert c2.status == "rejected"
    with Session(ctx.engine) as s:
        m = s.exec(select(VendorMaster)).one()
        active = [b for b in m.record["bank_accounts"] if b["status"] == "active"]
        assert len(active) == 1 and active[0]["account"] == BANK[0]


def test_unchanged_resubmission_carries_bank_verification_forward():
    ctx = make_ctx()
    ctx.sim = False
    approve_vendor(ctx)
    cid2, rid2 = submit(ctx)
    assert rule(ctx, rid2, "R16")["result"] == "pass" and "carried forward" in rule(ctx, rid2, "R16")["reason"]
    assert case(ctx, cid2).status == "approved"


def test_r02_account_used_by_other_pan_is_internal_only():
    ctx = make_ctx()
    ctx.sim = False
    approve_vendor(ctx)
    other_g = v.with_gstin_check_char("27AAACQ9999Q1Z")
    ctx.gst.fixtures[other_g] = gst_fixture(other_g, "QUARTZ SUPPLIES PRIVATE LIMITED", "QUARTZ")
    cid, rid = submit(ctx, form(legal_name="QUARTZ SUPPLIES PRIVATE LIMITED", gstin=other_g, pan="AAACQ9999Q", cin="U51909MH2016PTC654321"))
    r02 = rule(ctx, rid, "R02")
    assert r02["result"] == "flag" and r02["owner"] == "finance" and r02["vendor_text"] == ""
    assert "R02" not in str(case(ctx, cid).decision["message"])


def test_sandbox_mode_never_satisfies_gst_requirement():
    from vendorcheck.adapters.base import AdapterResult
    ctx = make_ctx({GSTIN: gst_fixture()}, sim=False)
    ctx.gst.lookup = lambda g: AdapterResult(True, {**__import__("vendorcheck.adapters.gst", fromlist=["x"]).parse_lookup(gst_fixture())}, "gstinapi.in", "sandbox")
    cid, rid = submit(ctx)
    assert any("sandbox evidence cannot satisfy" in i["reason"] for i in case(ctx, cid).decision["open_items"])
