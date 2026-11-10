"""FastAPI app: server-rendered pages, HTMX polling for the live run view, Alpine for small interactions."""
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, SQLModel, select

from .. import bench, config, db, pipeline, workflow
from .. import countries as cn
from .. import policy as policy_mod
from .. import simulation
from .. import validators as v
from ..adapters import ifsc as ifsc_adapter
from ..context import default_ctx, sources_status
from ..examples import EXAMPLES, SAMPLE_FILES
from ..models import Case, Run, Task, VendorMaster, Version, utcnow
from ..reader import ReaderUnavailable
from ..storage import allowed, store_bytes
from ..workflow import USERS, WorkflowError, latest_version, user_of
from . import views

HERE = Path(__file__).parent
FORM_FIELDS = ["country", "legal_name", "address", "gstin", "pan", "cin", "tax_id", "bank_account", "bank_account_confirm", "iban", "swift", "routing_code", "ifsc", "account_holder",
               "contact_name", "contact_email", "contact_phone", "udyam_number",
               "vendor_type", "expense_category", "department_owner", "negotiated_terms", "system_terms"]
OFFICIAL = {
    "gst": ("GST portal: Search Taxpayer", "https://services.gst.gov.in/services/searchtp", "gstin", "GSTIN"),
    "udyam": ("Udyam Registration: Verify", "https://udyamregistration.gov.in/Udyam_Verify.aspx", "udyam_number", "Udyam number"),
    "mca": ("MCA master data (may need a free login)", "https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html", "cin", "CIN"),
    "pan": ("Income Tax e-filing: Verify Your PAN", "https://eportal.incometax.gov.in/iec/foservices/#/pre-login/verifyYourPAN", "pan", "PAN"),
    "taxid": ("Official tax register for the vendor's country", "", "tax_id", "Tax ID"),
}
ASSIST_FIELDS = {
    "gst": ["gstin", "legal_name", "trade_name", "status", "taxpayer_type", "constitution", "registration_date", "cancellation_date"],
    "udyam": ["udyam_number", "enterprise_name", "enterprise_type", "status", "date_of_incorporation"],
    "mca": ["cin", "company_name", "company_status", "date_of_incorporation", "registered_state"],
    "pan": ["pan", "pan_status", "name_as_per_pan"],
    "taxid": ["tax_id", "legal_name", "status"],
}


def create_app(ctx=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config.ensure_dirs()
        if not hasattr(app.state, "ctx"):
            app.state.ctx = ctx or default_ctx()
        if not ifsc_adapter.dataset_ready():
            print("IFSC dataset missing: run `make setup` (or python -m vendorcheck.adapters.ifsc --download)")
        resumed = pipeline.recover_runs(app.state.ctx)
        if resumed:
            print(f"Resumed {len(resumed)} unfinished run(s)")
        yield

    app = FastAPI(title="VendorCheck", lifespan=lifespan)
    if ctx is not None:
        app.state.ctx = ctx
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters.update({"upfirst": lambda s: (s[:1].upper() + s[1:]) if s else s, "mask_ids": views.mask_ids, "ist": views.ist, "dur": views.dur, "mask": v.mask})
    def asset_v() -> int:
        """Changes whenever the stylesheet or script changes, so a browser never keeps an old copy."""
        return max(int((HERE / "static" / n).stat().st_mtime) for n in ("app.css", "app.js"))
    templates.env.globals.update({"STAGE_ORDER": views.STAGE_ORDER, "asset_v": asset_v})

    def sim_for(st):
        """The simulated-registry context, built once per base context."""
        if getattr(st, "sim_ctx", None) is None or getattr(st, "sim_base", None) is not st.ctx:
            st.sim_ctx, st.sim_base = simulation.sim_ctx(st.ctx), st.ctx
        simulation.sync_policy(st.sim_ctx, st.ctx)
        return st.sim_ctx

    def case_of(request: Request, s: Session):
        """The case a request is about, from its path: /cases/{id}, /runs/{id}, /tasks/{id} or the vendor portal /v/{token}."""
        p = request.path_params
        if "case_id" in p:
            return s.get(Case, int(p["case_id"]))
        if "run_id" in p:
            run = s.get(Run, int(p["run_id"]))
            return s.get(Case, run.case_id) if run else None
        if "task_id" in p:
            task = s.get(Task, int(p["task_id"]))
            return s.get(Case, task.case_id) if task else None
        if "token" in p:
            return s.exec(select(Case).where(Case.token == p["token"])).first()
        return None

    def C(request: Request):
        """The context for this request: the real one, or the simulated one for a case that was submitted as a simulation."""
        st = request.app.state
        cached = getattr(request.state, "ctx_cached", None)
        if cached is not None:
            return cached
        ctx = st.ctx
        if request.path_params:
            with Session(st.ctx.engine) as s:
                case = case_of(request, s)
                if case is not None and case.sim:
                    ctx = sim_for(st)
        request.state.ctx_cached = ctx
        return ctx

    def me(request: Request) -> dict:
        return user_of(request.cookies.get("vc_user", "priya"))

    def render(request: Request, name: str, status_code: int = 200, **kw):
        base = dict(user=me(request), users=list(USERS.values()), sources=sources_status(C(request)), path=request.url.path, flash=request.query_params.get("flash", ""),
                    error=request.query_params.get("error", ""))
        return templates.TemplateResponse(request, name, {**base, **kw}, status_code=status_code)

    def back(request: Request, **q) -> RedirectResponse:
        dest = request.headers.get("referer", "/")
        return RedirectResponse(dest.split("?")[0] + ("?" + "&".join(f"{k}={v_}" for k, v_ in q.items()) if q else ""), status_code=303)

    # ---------------- pages ----------------
    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, status: str = "", waiting: str = "", q: str = ""):
        with Session(C(request).engine, expire_on_commit=False) as s:
            return render(request, "dashboard.html", rows=views.case_rows(s, status, waiting, q), kpi=views.kpis(s), f={"status": status, "waiting": waiting, "q": q})

    @app.get("/new", response_class=HTMLResponse)
    def new_form(request: Request, prefill: str = ""):
        pre = {}
        if prefill:
            try:
                pre = {k: str(val) for k, val in json.loads(prefill).items() if k in FORM_FIELDS}
            except ValueError:
                pre = {}
        pol = C(request).policy
        return render(request, "new.html", examples=EXAMPLES, examples_json=json.dumps(EXAMPLES).replace("</", "<\\/"), prefill_json=json.dumps(pre), countries=cn.COUNTRIES,
                      details_on={k: policy_mod.detail_on(pol, k) for k in policy_mod.DETAIL_KEYS}, custom_details=policy_mod.custom_details(pol))

    # ---------------- test bench ----------------
    @app.get("/bench", response_class=HTMLResponse)
    def bench_page(request: Request):
        st = request.app.state
        return render(request, "bench.html", results=getattr(st, "bench", None), mut=getattr(st, "mut", None), examples=EXAMPLES, mutations=bench.MUTATIONS)

    @app.post("/bench/run")
    def bench_run(request: Request):
        request.app.state.bench = bench.run_all()
        return RedirectResponse("/bench", 303)

    @app.post("/bench/mutate")
    def bench_mutate(request: Request, example: str = Form("zoho"), kind: str = Form("flip_gstin")):
        if example in EXAMPLES and kind in bench.MUTATIONS:
            request.app.state.mut = {"example": example, "kind": kind, **bench.run_mutation(example, kind)}
        return RedirectResponse("/bench", 303)

    @app.post("/submit")
    async def submit(request: Request):
        form = await request.form()
        typed = {k: (form.get(k) or "").strip() for k in FORM_FIELDS + ["x_" + d["key"] for d in policy_mod.custom_details(C(request).policy)]}
        typed["msme"] = form.get("msme") == "yes"
        files = []
        for up in form.getlist("files"):
            if getattr(up, "filename", ""):
                if not allowed(up.filename):
                    return RedirectResponse(f"/new?error=File type of {up.filename} is not supported (PDF, PNG, JPG, HEIC, WebP, TIFF)", 303)
                files.append(store_bytes(await up.read(), up.filename))
        for name in filter(None, (form.get("sample_files") or "").split(",")):
            if name in SAMPLE_FILES and (config.SAMPLES_DIR / name).exists():
                files.append(store_bytes((config.SAMPLES_DIR / name).read_bytes(), name))
        if not files and not any(typed[k] for k in ("legal_name", "gstin", "pan")):
            return RedirectResponse("/new?error=Add a document or fill in at least the legal name, GSTIN or PAN", 303)
        ctx = sim_for(request.app.state) if form.get("simulate") == "1" else C(request)      # a simulated test case runs against the simulated registry
        cid, vid = workflow.create_case(ctx, {k: val for k, val in typed.items() if val not in ("", False)}, files, actor=me(request)["name"])
        rid = pipeline.start_run(ctx, cid, vid)
        return RedirectResponse(f"/runs/{rid}", 303)

    @app.get("/api/check/{field}", response_class=HTMLResponse)
    def inline_check(field: str, request: Request):
        val = request.query_params.get(field, "")
        if not val.strip():
            return ""
        country = (request.query_params.get("country") or "").upper()
        if field in ("tax_id", "iban", "swift", "routing_code"):
            if field == "tax_id" and country:
                r = cn.check_tax_id(country, val)
                if r.ok:
                    return f'<span class="text-emerald-700">✓ valid {cn.name_of(country)} {r.id_type} format · format check only, a person confirms it on the official register</span>'
                return f'<span class="text-amber-700">⚠ {r.message}</span>'
            if field == "iban":
                return ('<span class="text-emerald-700">✓ valid IBAN (' + cn.name_of(cn.flat(val)[:2]) + ')</span>') if cn.iban_ok(val) else '<span class="text-amber-700">⚠ not a valid IBAN: check digits or length are wrong</span>'
            if field == "swift":
                ok = bool(cn.SWIFT_RE.match(cn.flat(val)))
                return '<span class="text-emerald-700">✓ valid SWIFT/BIC shape</span>' if ok else '<span class="text-amber-700">⚠ a SWIFT/BIC is 8 or 11 characters</span>'
            if field == "routing_code":
                if country == "US":
                    return '<span class="text-emerald-700">✓ valid ABA routing number</span>' if cn.aba_ok(val) else '<span class="text-amber-700">⚠ fails the ABA check digit</span>'
                return ""
        r = {"gstin": lambda: v.check_gstin(val), "pan": lambda: v.check_pan(val), "ifsc": lambda: v.check_ifsc_format(val),
             "cin": lambda: v.check_cin(val), "udyam_number": lambda: v.check_udyam(val),
             "bank_account": lambda: v.check_account(val, request.query_params.get("bank_account_confirm"))}.get(field, lambda: v.Result(True))()
        if field == "bank_account_confirm":
            r = v.check_account(request.query_params.get("bank_account", ""), val)
        if r.ok:
            extra = ""
            if field == "gstin" and r.code != "sandbox":
                extra = f" · {v.state_of_gstin(val)} · PAN inside: {v.mask(v.pan_from_gstin(val))}"
            if field == "pan":
                extra = f" · {v.pan_type(val)}"
            return f'<span class="text-emerald-700">✓ looks valid{extra}</span>'
        return f'<span class="text-amber-700">⚠ {r.message}</span>'

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_page(run_id: int, request: Request):
        with Session(C(request).engine, expire_on_commit=False) as s:
            view = views.run_view(s, run_id, me(request))
            if not view:
                return HTMLResponse("Run not found", 404)
        return render(request, "run.html", **view)

    @app.get("/runs/{run_id}/fragment", response_class=HTMLResponse)
    def run_fragment(run_id: int, request: Request):
        with Session(C(request).engine, expire_on_commit=False) as s:
            view = views.run_view(s, run_id, me(request))
        return render(request, "_run.html", **view)

    @app.get("/cases/{case_id}", response_class=HTMLResponse)
    def case_page(case_id: int, request: Request, tab: str = "latest"):
        with Session(C(request).engine, expire_on_commit=False) as s:
            cv = views.case_view(s, case_id)
            if not cv["case"]:
                return HTMLResponse("Case not found", 404)
            rv = views.run_view(s, cv["latest_run"].id, me(request)) if (tab == "latest" and cv["latest_run"]) else {}
            diffs = {ver.id: ver for ver in cv["versions"]}
        return render(request, "case.html", tab=tab, cv=cv, diffs=diffs, **rv) if tab == "latest" else render(request, "case.html", tab=tab, cv=cv, diffs=diffs, **{"case": cv["case"]})

    @app.get("/queue", response_class=HTMLResponse)
    def queue(request: Request, owner: str = ""):
        u = me(request)
        with Session(C(request).engine, expire_on_commit=False) as s:
            rows = []
            for t in s.exec(select(Task).where(Task.status.in_(["open", "resolved"])).order_by(Task.created_at)).all():
                case = s.get(Case, t.case_id)
                if case.sim or case.status in ("approved", "rejected"):
                    continue
                if owner and t.owner != owner:
                    continue
                rows.append({"task": t, "case": case, "mine": workflow.can_resolve(u, t), "approve": workflow.can_approve(u, t)})
        rows.sort(key=lambda r: (not (r["mine"] or r["approve"]), r["task"].created_at))
        return render(request, "queue.html", rows=rows, owner=owner)

    @app.get("/vendors", response_class=HTMLResponse)
    def vendors(request: Request):
        with Session(C(request).engine, expire_on_commit=False) as s:
            return render(request, "vendors.html", vendors=list(s.exec(select(VendorMaster).order_by(VendorMaster.id)).all()))

    @app.get("/vendors/{code}", response_class=HTMLResponse)
    def vendor_detail(code: str, request: Request):
        with Session(C(request).engine, expire_on_commit=False) as s:
            m = s.exec(select(VendorMaster).where(VendorMaster.vendor_code == code)).first()
            cases = [s.get(Case, i) for i in (m.record.get("case_ids", []) if m else [])]
        if not m:
            return HTMLResponse("Vendor not found", 404)
        return render(request, "vendor_detail.html", m=m, rec=m.record, cases=cases)

    # ---------------- actions ----------------
    @app.post("/role")
    def set_role(request: Request, role: str = Form("priya")):
        resp = back(request)
        resp.set_cookie("vc_user", role if role in USERS else "priya", max_age=86400 * 30)
        return resp

    @app.post("/tasks/{task_id}/resolve")
    def resolve(task_id: int, request: Request, outcome: str = Form(""), method: str = Form(""), note: str = Form("")):
        try:
            workflow.resolve_task(C(request), task_id, me(request)["key"], outcome, method, note)
            return back(request, flash="Recorded. A second person must approve before anything changes.")
        except WorkflowError as e:
            return back(request, error=str(e))

    @app.post("/tasks/{task_id}/approve")
    def approve(task_id: int, request: Request, decision: str = Form("approve")):
        try:
            workflow.approve_task(C(request), task_id, me(request)["key"], approve=(decision == "approve"))
            return back(request, flash="Approved." if decision == "approve" else "Sent back to the resolver.")
        except WorkflowError as e:
            return back(request, error=str(e))

    @app.post("/cases/{case_id}/retry")
    def retry(case_id: int, request: Request):
        rid = workflow.retry_case(C(request), case_id, me(request)["key"])
        return RedirectResponse(f"/runs/{rid}", 303)

    @app.post("/cases/{case_id}/commercial")
    async def commercial(case_id: int, request: Request):
        form = await request.form()
        try:
            rid = workflow.set_commercial(C(request), case_id, me(request)["key"], {k: form.get(k) for k in workflow.COMMERCIAL_KEYS})
        except WorkflowError as e:
            return back(request, error=str(e))
        return RedirectResponse(f"/runs/{rid}", 303)

    @app.post("/cases/{case_id}/verify-pan")
    def verify_pan(case_id: int, request: Request):
        problem = workflow.verify_pan_live(C(request), case_id, me(request)["key"])
        if problem:
            return back(request, error=problem)
        with Session(C(request).engine) as s:
            rid = views.latest_run(s, case_id).id
        return RedirectResponse(f"/runs/{rid}", 303)

    @app.post("/cases/{case_id}/filing-history")
    def filing_history(case_id: int, request: Request):
        problem = workflow.fetch_filing_history(C(request), case_id, me(request)["key"])
        if problem:
            return back(request, error=problem)
        with Session(C(request).engine) as s:
            rid = views.latest_run(s, case_id).id
        return RedirectResponse(f"/runs/{rid}", 303)

    # ---------------- assisted official check ----------------
    def assist_ctx(case_id: int, source: str, request: Request) -> dict:
        title, url, idfield, label = OFFICIAL[source]
        with Session(C(request).engine, expire_on_commit=False) as s:
            ver = latest_version(s, case_id)
            case = s.get(Case, case_id)
            ident = ver.profile.get("values", {}).get(idfield) or ver.declared.get(idfield, "")
        if source == "taxid":
            country = (ver.profile.get("values", {}).get("country") or ver.declared.get("country") or "").upper()
            title, url = cn.SITES.get(country, ("The tax authority's online register", ""))
            title = f"{title} ({cn.name_of(country)})"
        return {"case": case, "source": source, "title": title, "url": url, "label": label, "ident": ident, "fields": ASSIST_FIELDS[source], "extracted": None}

    @app.get("/cases/{case_id}/assist/{source}", response_class=HTMLResponse)
    def assist_page(case_id: int, source: str, request: Request):
        return render(request, "assist.html", **assist_ctx(case_id, source, request))

    @app.post("/cases/{case_id}/assist/{source}/extract", response_class=HTMLResponse)
    async def assist_extract(case_id: int, source: str, request: Request):
        form = await request.form()
        up = form.get("screenshot")
        a = assist_ctx(case_id, source, request)
        if not getattr(up, "filename", ""):
            return render(request, "assist.html", error="Choose or paste a screenshot first.", **a)
        shot = store_bytes(await up.read(), up.filename or "screenshot.png")
        notice = ""
        try:
            fields = C(request).reader.read_screenshot(shot, source)
        except ReaderUnavailable as e:
            fields, notice = {}, f"The reader could not extract the fields ({e}). You can type them from the screenshot yourself."
        a.update(extracted={k: fields.get(k, "") for k in ASSIST_FIELDS[source]}, shot=shot, notice=notice, looks_official=fields.get("_looks_official", "unknown"))
        return render(request, "assist.html", **a)

    @app.post("/cases/{case_id}/assist/{source}/save")
    async def assist_save(case_id: int, source: str, request: Request):
        form = await request.form()
        a = assist_ctx(case_id, source, request)
        fields = {k: (form.get(f"f_{k}") or "").strip() for k in ASSIST_FIELDS[source]}
        shot = {"sha256": form.get("shot_sha"), "name": form.get("shot_name")}
        shown = fields.get(OFFICIAL[source][2], "") or fields.get({"gst": "gstin", "mca": "cin"}.get(source, OFFICIAL[source][2]), "")
        if shown and v.clean(shown) != v.clean(a["ident"]):
            return render(request, "assist.html", error=f"The screenshot shows {shown}, not {a['ident']}. Check you looked up the right identifier.",
                          extracted=fields, shot=shot, **{k: val for k, val in a.items() if k != "extracted"})
        workflow.save_assisted(C(request), case_id, source, a["ident"], fields, shot, me(request)["key"])
        return RedirectResponse(f"/cases/{case_id}?flash=Saved as assisted evidence. A second person must approve it before it counts.", 303)

    # ---------------- vendor portal ----------------
    def field_labels(ctx):
        return {**FIELD_LABEL, **{"x_" + d["key"]: d["label"] for d in policy_mod.custom_details(ctx.policy)}}

    FIELD_LABEL = {"country": "Country the business is based in", "tax_id": "Tax ID (EIN, VAT number…)", "iban": "IBAN", "swift": "SWIFT/BIC",
                   "routing_code": "Routing number (ABA) or sort code", "legal_name": "Legal business name", "gstin": "GSTIN", "pan": "PAN", "cin": "CIN", "bank_account": "Bank account number",
                   "bank_account_confirm": "Confirm bank account number", "ifsc": "IFSC", "contact_name": "Contact name", "contact_email": "Contact email",
                   "contact_phone": "Contact phone", "udyam_number": "Udyam number"}

    def portal_case(request: Request, token: str):
        with Session(C(request).engine, expire_on_commit=False) as s:
            return s.exec(select(Case).where(Case.token == token)).first()

    @app.get("/v/{token}", response_class=HTMLResponse)
    def portal(token: str, request: Request):
        case = portal_case(request, token)
        if not case:
            return HTMLResponse("This link is not valid.", 404)
        # always carry every key: on an empty dict Jinja's msg['items'] would resolve to the dict's .items() method
        msg = {"items": [], "fields": [], "upload": False, "intro": "", **((case.decision or {}).get("message") or {})}
        rej = (case.decision or {}).get("rejected") or {}
        return templates.TemplateResponse(request, "portal.html", {"case": case, "msg": msg, "labels": field_labels(C(request)), "sent": request.query_params.get("sent", ""),
                                                                    "status": case.status, "reapply": bool(rej.get("reapply"))})

    @app.post("/v/{token}")
    async def portal_submit(token: str, request: Request):
        case = portal_case(request, token)
        if not case:
            return HTMLResponse("This link is not valid.", 404)
        form = await request.form()
        updates = {k: (form.get(k) or "").strip() for k in field_labels(C(request)) if (form.get(k) or "").strip()}
        files = [store_bytes(await up.read(), up.filename) for up in form.getlist("files") if getattr(up, "filename", "") and allowed(up.filename)]
        if not updates and not files:
            return RedirectResponse(f"/v/{token}?sent=none", 303)
        ctx = C(request)
        vid = workflow.new_version(ctx, case.id, updates, files, created_by="vendor", actor=f"Vendor ({case.display_name})")
        pipeline.start_run(ctx, case.id, vid, trigger="vendor correction")
        return RedirectResponse(f"/v/{token}?sent=1", 303)

    # ---------------- files, settings ----------------
    @app.get("/files/{sha}/{name}")
    def files(sha: str, name: str):
        p = config.UPLOAD_DIR / sha / Path(name).name
        return FileResponse(p) if p.exists() and len(sha) == 64 else Response(status_code=404)

    @app.get("/pagepng/{sha}/{page}")
    def page_png(sha: str, page: int, s: str = ""):
        """One page of an uploaded file as a PNG (thumbnail with ?s=thumb), for the document viewer."""
        d = config.UPLOAD_DIR / sha
        files_ = [p for p in d.iterdir() if p.is_file()] if len(sha) == 64 and sha.isalnum() and d.exists() else []
        if not files_:
            return Response(status_code=404)
        p = files_[0]
        if p.read_bytes()[:4] == b"%PDF":
            import pymupdf
            doc = pymupdf.open(p)
            if not 1 <= page <= len(doc):
                return Response(status_code=404)
            return Response(doc[page - 1].get_pixmap(dpi=40 if s == "thumb" else 120).tobytes("png"), media_type="image/png")
        import io
        from PIL import Image, ImageOps
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:   # noqa: BLE001
            pass
        img = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        img.thumbnail((300, 300) if s == "thumb" else (1600, 1600))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return Response(buf.getvalue(), media_type="image/png")

    @app.get("/samples/{name}")
    def sample(name: str):
        p = config.SAMPLES_DIR / name
        return FileResponse(p) if name in SAMPLE_FILES and p.exists() else Response(status_code=404)

    @app.get("/settings", response_class=HTMLResponse)
    def settings(request: Request):
        ctx = C(request)
        cfg = {"GEMINI_API_KEY": bool(config.groq_key() or config.gemini_key() or config.openrouter_key()), "GEMINI_MODEL": config.gemini_model(), "GSTINAPI_KEY": bool(config.gstin_key()),
               "CASHFREE": bool(config.cashfree_id() and config.cashfree_secret()), "CASHFREE_ENV": config.cashfree_env()}
        return render(request, "settings.html", cfg=cfg, outage=db.get_kv(ctx.engine, "simulate_gst_outage") == "1", credits=db.get_kv(ctx.engine, "gst_credits_remaining"),
                      pol=ctx.policy, items_ui=policy_mod.items_for_ui(ctx.policy), item_presets={k: {"label": l, "format": f, "words": ", ".join(w), "applies": ap} for k, (l, f, w, ap) in policy_mod.ITEM_PRESETS.items()},
                      builtin_docs=policy_mod.BUILTIN_DOCS, doc_presets={k: {"label": l, "keywords": ", ".join(w), "applies": a} for k, (l, w, a) in policy_mod.DOC_PRESETS.items()},
                      doc_applies=policy_mod.APPLIES, doc_on={k: policy_mod.doc_enabled(ctx.policy, k) for k in policy_mod.BUILTIN_DOCS},
                      custom_items=[{"label": d["label"], "keywords": ", ".join(d["keywords"]), "need": d["need"], "applies": d["applies"]} for d in policy_mod.custom_docs(ctx.policy)],
                      detail_keys=policy_mod.DETAIL_KEYS, detail_on={k: policy_mod.detail_on(ctx.policy, k) for k in policy_mod.DETAIL_KEYS},
                      detail_presets={k: {"label": l, "format": f, "applies": a} for k, (l, f, a, h) in policy_mod.DETAIL_PRESETS.items()},
                      custom_detail_items=[{"label": d["label"], "format": d["format"], "required": "yes" if d["required"] else "no", "applies": d["applies"]} for d in policy_mod.custom_details(ctx.policy)],
                      reqs=policy_mod.REQUIREMENTS, evidence_label=policy_mod.EVIDENCE_LABEL, doc_modes=policy_mod.DOCUMENT_MODES,
                      policy_changed=db.get_kv(ctx.engine, "policy_changed"),
                      ifsc=ifsc_adapter.release_label(), result=request.query_params.get("result", ""))

    @app.post("/settings/policy")
    async def save_policy_route(request: Request):
        ctx = C(request)
        form = await request.form()
        new, errors = policy_mod.policy_from_form(form, ctx.policy)
        policy_mod.save_policy(new)
        ctx.policy.clear()
        ctx.policy.update(new)
        db.set_kv(ctx.engine, "policy_changed", f"{me(request)['name']} · {views.ist(utcnow(), '%d %b %Y, %H:%M')}")
        msg = "Policy saved. It applies from the next verification run." + ((" " + " ".join(errors)) if errors else "")
        return RedirectResponse(f"/settings?result={quote(msg)}#policy", 303)

    @app.post("/settings/policy/restore")
    def restore_policy(request: Request):
        ctx = C(request)
        fresh = deepcopy(policy_mod.DEFAULTS)
        policy_mod.save_policy(fresh)
        ctx.policy.clear()
        ctx.policy.update(fresh)
        db.set_kv(ctx.engine, "policy_changed", f"{me(request)['name']} · {views.ist(utcnow(), '%d %b %Y, %H:%M')} (defaults restored)")
        return RedirectResponse(f"/settings?result={quote('Policy restored to the defaults.')}#policy", 303)

    @app.post("/settings/outage")
    def set_outage(request: Request, on: str = Form("0")):
        db.set_kv(C(request).engine, "simulate_gst_outage", "1" if on == "1" else "0")
        return RedirectResponse("/settings", 303)

    @app.post("/settings/test-gst")
    def test_gst(request: Request):
        res = C(request).gst.lookup(v.SANDBOX_GSTIN)
        msg = (f"Connected. The sandbox GSTIN returned '{res.fields.get('legal_name')}' (mode {res.mode}, free, never used to verify a real vendor)."
               if res.ok else f"Not connected: {res.message}")
        return RedirectResponse(f"/settings?result={msg}", 303)

    @app.post("/settings/reset")
    def reset(request: Request):
        eng = C(request).engine
        SQLModel.metadata.drop_all(eng)
        SQLModel.metadata.create_all(eng)
        return RedirectResponse("/settings?result=Demo data cleared. Vendor master, cases and caches are empty again.", 303)

    return app


def get_app() -> FastAPI:
    return create_app()
