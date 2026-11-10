"""Test bench: runs the scenario suite on RECORDED / SYNTHETIC evidence at zero credits.

Isolation: every scenario runs in its own in-memory database with a simulation policy that also accepts
`recorded` evidence. Results are labelled SIMULATED and nothing touches the real cases or vendor master.
Real evidence never takes this path: the real policy never accepts `recorded` or `sandbox`.

Vendors here are FICTIONAL and their GST responses are synthetic (engine logic only). Real-vendor scenarios
that stop at an offline check (E2, E3) use the real examples; scenarios needing a live GST answer for a real
vendor appear only once real responses are captured into fixtures/gst/ (scripts/capture_fixtures.py)."""
import time
from dataclasses import dataclass, field

from sqlmodel import Session, select

from . import config, db, pipeline, storage, validators as v, workflow
from .adapters.gst import RecordedGst
from .context import Ctx
from .examples import EXAMPLES
from .models import Case, StageEvent, Task, VendorMaster
from .policy import load_policy, simulation_policy
from .reader import StaticReader

# ----- fictional vendor -----
PAN, NAME, CIN = "AAACB1234C", "BLUE HERON TRADING PRIVATE LIMITED", "U51909MH2015PTC123456"
GSTIN = v.with_gstin_check_char("27AAACB1234C1Z")
BANK = ("50100123456789", "HDFC0000001")
FORM = dict(legal_name=NAME, gstin=GSTIN, pan=PAN, cin=CIN, bank_account=BANK[0], bank_account_confirm=BANK[0], ifsc=BANK[1],
            contact_name="Asha Rao", contact_email="asha@blueheron.example", contact_phone="9000000001",
            vendor_type="goods", expense_category="Raw materials", department_owner="Procurement", negotiated_terms="Net 45", system_terms="45")


def gst_fx(gstin=GSTIN, legal=NAME, trade="BLUE HERON TRADING", status="Active", ttype="Regular", cancel=None):
    return {"success": True, "_synthetic": True, "gstin": gstin, "data": {
        "gstin": gstin, "legal_name": legal, "trade_name": trade, "status": status, "taxpayer_type": ttype, "business_constitution": "Private Limited Company",
        "registration_date": "2018-01-01", "cancellation_date": cancel, "state_code": gstin[:2], "address": "1 Test Road", "pincode": "400001",
        "einvoice_status": "Yes", "block_status": "Unblocked"}}


@dataclass
class Step:
    typed: dict | None = None            # a new submission (None = apply `actions` to the previous case)
    correct: dict | None = None          # vendor corrects fields -> new version of the previous case
    files: list = field(default_factory=list)
    actions: list = field(default_factory=list)     # ("resolve", key, user, outcome) / ("approve", key, user)
    expect: dict = field(default_factory=dict)      # status, waiting_on, rules {rule: result}, gst_calls
    note: str = ""


@dataclass
class Scenario:
    id: str
    title: str
    covers: str
    steps: list[Step]
    fixtures: dict = field(default_factory=dict)
    reader: object = None
    policy: dict = field(default_factory=dict)
    real: bool = False                   # uses a real vendor's public identifiers (offline checks only)


def _pdf(name: str) -> dict:
    import pymupdf
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "Typed document with enough selectable text to count as a text layer for the bench scenarios.")
    return storage.store_bytes(d.tobytes(), name)


RULE_NAME = {"R01": "Duplicate check", "R03": "Required details", "R06": "GSTIN format", "R08": "PAN inside GSTIN", "R09": "Bank format", "R10": "CIN",
             "R11": "GST registry", "R12": "Legal name", "R16": "Bank account", "R18": "Bank change", "R19": "Blocklist", "R20": "Source available",
             "R21": "Taxpayer type", "R23": "Country of tax ID", "R26": "Required documents", "X2": "Account holder name"}


def _documents_scenario() -> Scenario:
    """Typed details AND every required document attached, all consistent: the complete happy path."""
    f = _pdf("blue-heron-document-pack.pdf")
    kinds = ["vendor_registration_form", "pan_card", "gst_certificate", "cancelled_cheque_or_bank_letter", "address_proof", "incorporation_or_name_change_certificate"]
    pages = [{"page": i, "doc_type": k, "legible": True, "handwritten": False, "note": ""} for i, k in enumerate(kinds, 1)]
    addr = "1 Test Road Mumbai Maharashtra 400001"

    def fl(field, value, page):
        return {"field": field, "value": value, "page": page, "doc_type": kinds[page - 1], "snippet": value}
    fields = [fl("legal_name", NAME, 1), fl("pan", PAN, 1), fl("gstin", GSTIN, 1), fl("cin", CIN, 1), fl("bank_account", BANK[0], 1), fl("ifsc", BANK[1], 1),
              fl("pan", PAN, 2), fl("legal_name", NAME, 2),
              fl("gstin", GSTIN, 3), fl("pan", PAN, 3), fl("legal_name", NAME, 3), fl("address", addr, 3),
              fl("bank_account", BANK[0], 4), fl("ifsc", BANK[1], 4), fl("account_holder", NAME, 4),
              fl("address", addr, 5),
              fl("cin", CIN, 6), fl("legal_name", NAME, 6)]
    reader = StaticReader({f["name"]: {"pages": pages, "fields": fields, "hints": {}}})
    bank_ok = [("resolve", "R16", "arjun", "confirmed"), ("approve", "R16", "neha")]
    return Scenario("H2", "Happy path with all documents (fictional vendor)",
                    "Typed details plus registration form, PAN card, GST certificate, cancelled cheque, address proof and incorporation certificate; every document found and every detail agrees; two people approve",
                    [Step(dict(FORM, account_holder=NAME), files=[f], expect={"status": "pending", "waiting_on": "finance", "all_documents": True, "min_score": 100,
                                                   "rules": {"R26": "pass", "R11": "pass", "R06": "pass", "R08": "pass", "X2": "pass"}}),
                     Step(actions=bank_ok, expect={"status": "approved", "all_documents": True, "min_score": 100})],
                    {GSTIN: gst_fx()}, reader=reader, policy={"require_documents": "always"})


def _no_documents_scenario() -> Scenario:
    return Scenario("D1", "No documents provided", "Typed details only: noted as 'No documents provided', never blocked or called missing",
                    [Step(FORM, expect={"status": "pending", "waiting_on": "finance", "rules": {"R26": "info", "R11": "pass"}})],
                    {GSTIN: gst_fx()}, policy={"require_documents": "if_uploaded"})


def _rename_scenario(flip: bool) -> Scenario:
    f = _pdf("bench-rename-filing.pdf")
    fields = [{"field": "previous_name", "value": "STARLING DELIVERY LIMITED", "page": 1, "snippet": "Formerly known as Starling Delivery Limited"},
              {"field": "new_name", "value": "NOVA FOODS LIMITED", "page": 1, "snippet": "NOVA FOODS LIMITED (Formerly known as Starling Delivery Limited)"}]
    reader = StaticReader({f["name"]: {"pages": [{"page": 1, "doc_type": "stock_exchange_filing", "legible": True, "handwritten": False, "note": ""}], "fields": fields}})
    declared, gst = ("STARLING DELIVERY LIMITED", "NOVA FOODS LIMITED") if flip else ("NOVA FOODS LIMITED", "STARLING DELIVERY LIMITED")
    return Scenario(f"E1{'b' if flip else 'a'}", f"E1 renamed company, GST reads the {'new' if flip else 'old'} name",
                    "R12 explains a name mismatch from rename evidence, either way round",
                    [Step(dict(FORM, legal_name=declared, cin=""), files=[f], actions=[("resolve", "R16", "arjun", "confirmed"), ("approve", "R16", "neha")],
                          expect={"status": "approved", "rules": {"R12": "note"}})], {GSTIN: gst_fx(legal=gst, trade=gst)}, reader)


def _sister() -> str:
    return v.with_gstin_check_char("27AABCZ7092H1Z")


def real_fixture_scenarios() -> list[Scenario]:
    """Scenarios that replay REAL captured responses. They exist only after scripts/capture_fixtures.py has run."""
    d = config.FIXTURE_DIR / "gst"
    have = lambda g: (d / f"{g}.json").exists()   # noqa: E731
    z, tcs = EXAMPLES["zoho"]["fields"], EXAMPLES["tcs"]["fields"]
    bank_ok = [("resolve", "R16", "arjun", "confirmed"), ("approve", "R16", "neha")]
    out = []
    if have("33AAACZ4322M1ZA"):
        out.append(Scenario("R1", "Zoho: recorded real GST response", "Real response replayed; every identifier check passes; waits on finance",
                            [Step(z, actions=bank_ok, expect={"status": "approved", "rules": {"R11": "pass", "R08": "pass"}})], real=True))
    if have("33AAACZ4322M1ZA") and have("33AABCZ7092H1Z3"):
        out.append(Scenario("R2", "E3 with real records", "Sister company GSTIN stops at the PAN match; the corrected GSTIN verifies",
                            [Step(EXAMPLES["zoho_lookalike"]["fields"], expect={"status": "pending", "waiting_on": "vendor", "rules": {"R08": "flag"}, "gst_calls": 0}),
                             Step(correct={"gstin": "33AAACZ4322M1ZA"}, expect={"rules": {"R08": "pass", "R11": "pass"}, "gst_calls": 1})], real=True))
    if have("24AAACR4849R1ZR"):
        out.append(Scenario("R3", "E2 with real records", "Tax-collector GSTIN flagged offline; the regular Gujarat GSTIN verifies",
                            [Step(tcs, expect={"status": "pending", "waiting_on": "vendor", "rules": {"R06": "flag"}, "gst_calls": 0}),
                             Step(correct={"gstin": "24AAACR4849R1ZR"}, expect={"rules": {"R06": "pass", "R11": "pass"}, "gst_calls": 1})], real=True))
    return out


def build_scenarios() -> list[Scenario]:
    z, lk, tcs = EXAMPLES["zoho"]["fields"], EXAMPLES["zoho_lookalike"]["fields"], EXAMPLES["tcs"]["fields"]
    bank_ok = [("resolve", "R16", "arjun", "confirmed"), ("approve", "R16", "neha")]
    return [
        _documents_scenario(), _no_documents_scenario(),
        Scenario("H1", "Happy path (fictional vendor)", "Seven stages; GST passes; waits on finance for the bank; two people approve",
                 [Step(FORM, expect={"status": "pending", "waiting_on": "finance", "rules": {"R11": "pass", "R06": "pass", "R08": "pass"}}),
                  Step(actions=bank_ok, expect={"status": "approved"})], {GSTIN: gst_fx()}),
        Scenario("E3", "Look-alike sister company (real Zoho example)", "PAN mismatch stops before any API call; vendor corrects GSTIN; version 2 passes",
                 [Step(lk, expect={"status": "pending", "waiting_on": "vendor", "rules": {"R08": "flag", "R11": "skip"}, "gst_calls": 0})], real=True),
        Scenario("E3v", "E3 correction loop (fictional vendor)", "Vendor fixes the GSTIN in version 2, which then runs and passes identity checks",
                 [Step(dict(FORM, gstin=_sister()), expect={"status": "pending", "waiting_on": "vendor", "rules": {"R08": "flag"}, "gst_calls": 0}),
                  Step(correct={"gstin": GSTIN}, expect={"status": "pending", "waiting_on": "finance", "rules": {"R08": "pass", "R11": "pass"}, "gst_calls": 1})],
                 {GSTIN: gst_fx()}),
        Scenario("E2", "Tax-collector GSTIN (real TCS example)", "Format check flags it instantly, no API credit; vendor supplies the regular GSTIN",
                 [Step(tcs, expect={"status": "pending", "waiting_on": "vendor", "rules": {"R06": "flag", "R11": "skip"}, "gst_calls": 0})], real=True),
        _rename_scenario(False), _rename_scenario(True),
        Scenario("E4", "Bank change on an approved vendor", "Bank change is challenged; contact on file says not our account; change rejected, old account stays active",
                 [Step(FORM, actions=bank_ok, expect={"status": "approved"}),
                  Step(dict(FORM, bank_account="026291800001191", bank_account_confirm="026291800001191", ifsc="YESB0000262"),
                       actions=[("resolve", "R18", "arjun", "reject"), ("approve", "R18", "neha")],
                       expect={"status": "rejected", "rules": {"R18": "flag", "R01": "note"}, "active_bank": BANK[0]})], {GSTIN: gst_fx()}),
        Scenario("N1", "Name differs from GST, no rename evidence", "Name mismatch goes to procurement",
                 [Step(FORM, expect={"status": "pending", "waiting_on": "procurement", "rules": {"R12": "flag"}})], {GSTIN: gst_fx(legal="OLD NAME TRADERS PRIVATE LIMITED", trade="OLD NAME")}),
        Scenario("G1", "GST registration cancelled", "GSTIN rejected with a route to reapply",
                 [Step(FORM, expect={"status": "rejected", "rules": {"R11": "reject"}})], {GSTIN: gst_fx(status="Cancelled", cancel="2024-01-01")}),
        Scenario("G2", "GST registration suspended", "Pending on the vendor",
                 [Step(FORM, expect={"status": "pending", "waiting_on": "vendor", "rules": {"R11": "flag"}})], {GSTIN: gst_fx(status="Suspended")}),
        Scenario("G3", "Composition taxpayer", "Passes with an accounts-payable condition",
                 [Step(FORM, actions=bank_ok, expect={"status": "approved", "rules": {"R21": "note"}, "conditions": 2})], {GSTIN: gst_fx(ttype="Composition")}),
        Scenario("S1", "GST source unreachable", "Pending, owned by the system, never a pass",
                 [Step(FORM, expect={"status": "pending", "waiting_on": "system", "rules": {"R20": "wait", "R11": "skip"}})], {}),
        Scenario("V1", "Required details missing", "Names what is missing",
                 [Step(dict(FORM, contact_name="", contact_email="", contact_phone=""), expect={"status": "pending", "waiting_on": "vendor", "rules": {"R03": "flag"}})], {GSTIN: gst_fx()}),
        Scenario("V2", "IFSC does not exist", "Pending on the vendor, no API call",
                 [Step(dict(FORM, ifsc="CNRR0002640"), expect={"status": "pending", "waiting_on": "vendor", "rules": {"R09": "flag"}, "gst_calls": 1})], {GSTIN: gst_fx()}),
        Scenario("V3", "CIN class does not fit the name", "Pending on the vendor",
                 [Step(dict(FORM, cin="U51909MH2015PLC123456"), expect={"status": "pending", "waiting_on": "vendor", "rules": {"R10": "flag"}})], {GSTIN: gst_fx()}),
        Scenario("B1", "PAN on the blocklist", "Rejected; the vendor message never says why",
                 [Step(FORM, expect={"status": "rejected", "rules": {"R19": "reject"}})], {GSTIN: gst_fx()}, policy={"blocklist": {"pans": [PAN], "accounts": []}}),
        Scenario("I1", "Says US, gives an Indian GSTIN", "Identifies the ID as Indian and flags the mismatch; no Indian source is called",
                 [Step(EXAMPLES["wrong_country"]["fields"], expect={"status": "pending", "waiting_on": "vendor", "rules": {"R23": "flag", "R11": "skip"}, "gst_calls": 0})], {}),
        Scenario("I2", "US vendor with a valid EIN", "Format passes but it is never called verified: a person checks the register, finance confirms the bank",
                 [Step(EXAMPLES["us_vendor"]["fields"], expect={"status": "pending", "waiting_on": "procurement", "rules": {"R09": "pass", "R11": "skip"}, "gst_calls": 0})], {}),
        Scenario("I3", "German vendor, French IBAN", "Flags the IBAN country against the claimed country",
                 [Step(EXAMPLES["eu_wrong_iban"]["fields"], expect={"status": "pending", "waiting_on": "vendor", "rules": {"R09": "flag"}, "gst_calls": 0})], {}),
        Scenario("W1", "Self-approval is refused", "The person who resolved an item cannot approve it",
                 [Step(FORM, actions=[("resolve", "R16", "arjun", "confirmed"), ("approve", "R16", "arjun")],
                       expect={"status": "pending", "refused": True})], {GSTIN: gst_fx()}),
    ]


def make_ctx(sc: Scenario) -> Ctx:
    pol = load_policy()
    pol["require_documents"] = "off"          # bench scenarios are about other rules unless they set it themselves
    for k, val in sc.policy.items():
        pol[k] = val
    gst = RecordedGst(dict(sc.fixtures))     # falls back to fixtures/gst/ (real captured responses) when present
    gst.calls = []
    orig = gst.lookup
    gst.lookup = lambda g: (gst.calls.append(g), orig(g))[1]
    return Ctx(engine=db.make_engine("sqlite://"), policy=simulation_policy(pol), gst=gst, reader=sc.reader or StaticReader({}), sim=False, enrich=False)


def _task_id(ctx, case_id, key):
    with Session(ctx.engine) as s:
        return next(t.id for t in s.exec(select(Task).where(Task.case_id == case_id, Task.key == key, Task.status.in_(["open", "resolved"]))).all())


def run_scenario(sc: Scenario) -> dict:
    t0 = time.monotonic()
    ctx = make_ctx(sc)
    rows, ok, case_id, last_gst = [], True, None, 0
    for i, st in enumerate(sc.steps, 1):
        problems, refused = [], False
        try:
            if st.typed is not None:
                case_id, vid = workflow.create_case(ctx, st.typed, st.files, actor="bench")
                rid = pipeline.start_run(ctx, case_id, vid, background=False)
            elif st.correct is not None:
                vid = workflow.new_version(ctx, case_id, st.correct, st.files, "vendor")
                rid = pipeline.start_run(ctx, case_id, vid, "vendor correction", background=False)
            else:
                rid = None
            for a in st.actions:
                try:
                    tid = _task_id(ctx, case_id, a[1])
                    if a[0] == "resolve":
                        workflow.resolve_task(ctx, tid, a[2], a[3], "bench", "")
                    else:
                        workflow.approve_task(ctx, tid, a[2], background=False)
                except workflow.WorkflowError:
                    refused = True
            with Session(ctx.engine) as s:
                case = s.get(Case, case_id)
                run = workflow.latest_run(s, case_id)
                checks = {c["rule"]: c["result"] for e in s.exec(select(StageEvent).where(StageEvent.run_id == run.id)).all() for c in e.checks}
                masters = s.exec(select(VendorMaster)).all()
                prof = workflow.latest_version(s, case_id).profile
            e = st.expect
            if e.get("all_documents"):
                req = [r for r in prof.get("checklist", []) if r["required"]]
                if not req or any(r["state"] != "found" for r in req):
                    problems.append("not every required document was found")
            if "min_score" in e:
                score = (prof.get("matrix") or {}).get("score")
                if score is None or score < e["min_score"]:
                    problems.append(f"consistency score {score}, expected at least {e['min_score']}")
            if "status" in e and case.status != e["status"]: problems.append(f"status {case.status} ≠ {e['status']}")
            if "waiting_on" in e and case.waiting_on != e["waiting_on"]: problems.append(f"waiting on {case.waiting_on or '—'} ≠ {e['waiting_on']}")
            for r, want in e.get("rules", {}).items():
                if checks.get(r) != want: problems.append(f"{RULE_NAME.get(r, r)} is {checks.get(r)}, expected {want}")
            if "gst_calls" in e and len(ctx.gst.calls) != e["gst_calls"]: problems.append(f"{len(ctx.gst.calls)} GST calls, expected {e['gst_calls']}")
            if "conditions" in e and len(case.decision.get("conditions", [])) < 1: problems.append("no condition recorded")
            if e.get("refused") and not refused: problems.append("self-approval was not refused")
            if "active_bank" in e:
                active = [b["account"] for b in (masters[0].record["bank_accounts"] if masters else []) if b["status"] == "active"]
                if active != [e["active_bank"]]: problems.append(f"active bank {active}")
            actual = f"{case.status}{' · ' + case.waiting_on if case.waiting_on else ''}"
            rows.append({"n": i, "expected": _fmt(e), "actual": actual + (" · " + ", ".join(f"{RULE_NAME.get(r, r)} {checks.get(r)}" for r in e.get('rules', {})) if e.get("rules") else ""), "ok": not problems, "problems": problems})
        except Exception as ex:   # noqa: BLE001
            rows.append({"n": i, "expected": _fmt(st.expect), "actual": f"error: {ex}", "ok": False, "problems": [str(ex)]})
        ok = ok and rows[-1]["ok"]
    return {"id": sc.id, "title": sc.title, "covers": sc.covers, "ok": ok, "rows": rows, "ms": int((time.monotonic() - t0) * 1000), "real": sc.real}


def _fmt(e: dict) -> str:
    s = e.get("status", "")
    if e.get("waiting_on"): s += f" · {e['waiting_on']}"
    if e.get("rules"): s += " · " + ", ".join(f"{RULE_NAME.get(r, r)} {x}" for r, x in e["rules"].items())
    if "gst_calls" in e: s += f" · {e['gst_calls']} GST calls"
    return s


def run_all() -> list[dict]:
    return [run_scenario(sc) for sc in build_scenarios() + real_fixture_scenarios()]


# ----- mutations: alter a real record to make a new test case -----
MUTATIONS = {
    "flip_gstin": ("Flip one GSTIN character", "R06 should flag a check-digit error"),
    "swap_pan": ("Swap in another vendor's PAN", "R08 should flag a PAN/GSTIN conflict"),
    "change_state": ("Change the GSTIN state code", "R06 should flag (state and check digit no longer agree)"),
}


def mutate(example_key: str, kind: str) -> dict:
    f = dict(EXAMPLES[example_key]["fields"])
    g = f["gstin"]
    if kind == "flip_gstin":
        f["gstin"] = g[:6] + ("7" if g[6] != "7" else "3") + g[7:]
    elif kind == "swap_pan":
        other = next(e["fields"]["pan"] for k, e in EXAMPLES.items() if e["fields"]["pan"] != f["pan"])
        f["pan"] = other
    elif kind == "change_state":
        f["gstin"] = ("27" if g[:2] != "27" else "29") + g[2:]
    return f


def run_mutation(example_key: str, kind: str) -> dict:
    """Run the mutated record through the pipeline in simulation: offline checks only, zero credits."""
    f = mutate(example_key, kind)
    sc = Scenario("M", MUTATIONS[kind][0], MUTATIONS[kind][1], [Step(f, expect={})], {})
    ctx = make_ctx(sc)
    cid, vid = workflow.create_case(ctx, f, [], actor="bench")
    rid = pipeline.start_run(ctx, cid, vid, background=False)
    with Session(ctx.engine) as s:
        flagged = [(c["rule"], c["result"], c["reason"]) for e in s.exec(select(StageEvent).where(StageEvent.run_id == rid)).all() for c in e.checks if c["result"] in ("flag", "reject")]
        case = s.get(Case, cid)
    return {"fields": f, "status": case.status, "waiting_on": case.waiting_on, "flagged": flagged, "gst_calls": len(ctx.gst.calls)}
