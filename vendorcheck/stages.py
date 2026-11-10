"""Stages 1-5 of the pipeline: Intake, Read, Validate, Verify, Reconcile.

Each stage function appends `Check`s to the RunState and returns a one-line summary.
Stages never decide a status (that is decide.py) and never invent data: a source that cannot answer
produces a pending R20 check, never a pass."""
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlmodel import Session

from . import extract
from . import master as vm
from . import countries as cn
from . import validators as v
from .adapters.base import AdapterResult
from .models import Case, Run, Version
from . import checklist as ck
from .policy import applies_to, custom_details, custom_docs, detail_on, disabled_fields, doc_enabled, format_ok
from .matrix import same_address, DOC_LABEL, Source as MSource, apply_coverage, build as build_matrix, unit_of
from .reader import CRITICAL, RECOGNISED, ReaderUnavailable, imagey_pages
from .rules import FLAG, INFO, NOTE, PASS, REJECT, SKIP, WAIT, Check, vtext

COMMERCIAL_FIELDS = ["vendor_type", "expense_category", "department_owner", "negotiated_terms", "system_terms"]
FIELDS = ["legal_name", "trade_name", "gstin", "pan", "cin", "tax_id", "address", *COMMERCIAL_FIELDS, "bank_account", "iban", "swift", "routing_code", "ifsc", "account_holder",
          "contact_name", "contact_email", "contact_phone", "udyam_number"]
CONFLICT_FIELDS = tuple(CRITICAL) + ("tax_id", "iban")      # numbers that must be the same on every document
LABELS = {"legal_name": "legal name", "trade_name": "trade name", "gstin": "GSTIN", "pan": "PAN", "cin": "CIN",
          "bank_account": "bank account number", "ifsc": "IFSC", "account_holder": "account holder", "tax_id": "tax ID", "iban": "IBAN",
          "swift": "SWIFT/BIC", "routing_code": "routing code", "country": "country"}
FORM_DOC = "vendor_registration_form"
RENAME_DOCS = {"incorporation_or_name_change_certificate", "stock_exchange_filing"}


@dataclass
class RunState:
    case: Case
    version: Version
    run: Run
    files: list[dict]
    typed: dict
    assisted: dict = field(default_factory=dict)            # source -> approved assisted evidence meta
    profile: dict = field(default_factory=dict)
    prov: dict = field(default_factory=dict)                 # field -> {side, ref, mode}
    unconfirmed: dict = field(default_factory=dict)          # field -> {reads, ref}
    reads: dict = field(default_factory=dict)
    renames: list = field(default_factory=list)
    doc_values: dict = field(default_factory=dict)           # field -> value read from non-form documents
    blocked: set = field(default_factory=set)
    derived_pan: str = ""
    master: Any = None
    matched_on: list = field(default_factory=list)
    gst: AdapterResult | None = None
    checks: dict = field(default_factory=dict)               # stage key -> [Check]
    evidence: list = field(default_factory=list)
    table: list = field(default_factory=list)
    country: str = ""
    country_inferred: bool = False
    checklist: list = field(default_factory=list)
    compliance: list = field(default_factory=list)      # your extra items: number and document status
    item_details: dict = field(default_factory=dict)    # document you added -> the details it states (name, address, dates)
    sources: list = field(default_factory=list)
    matrix: dict = field(default_factory=dict)
    doc_map: list = field(default_factory=list)
    cur: str = ""
    progress: Callable[[str], None] = lambda msg: None

    def add(self, c: Check) -> Check:
        c.stage = self.cur
        self.checks.setdefault(self.cur, []).append(c)
        return c

    def ev(self, fld: str, value, source: str, mode: str, ref: str = "", side: str = "", meta: dict | None = None):
        if value not in ("", None):
            self.evidence.append(dict(field=fld, value=str(value), source=source, mode=mode, ref=ref, side=side, meta=meta or {}))


def flagged(st: RunState, rule: str) -> bool:
    return any(c.rule == rule and c.blocking for cs in st.checks.values() for c in cs)


def truthy(x) -> bool:
    return str(x).strip().lower() in ("1", "true", "yes", "on", "y")


# ============ 1. INTAKE ============

def stage_intake(ctx, st: RunState) -> str:
    n = len(st.files)
    shown = ", ".join(f"{f['name']} ({f['sha256'][:8]}…)" for f in st.files) or "no files"
    st.add(Check("I1", PASS, name="Files stored with SHA-256, new version opened", found=f"Version {st.version.number}: {shown}",
                 mode="computed", source="Intake", reason="Every file is stored under its SHA-256 hash and never changed; a correction opens a new version."))
    with Session(ctx.engine) as s:
        dups = vm.search_duplicates(s, st.typed.get("pan", ""), st.typed.get("gstin", ""), st.typed.get("iban") or st.typed.get("bank_account", ""))
    found = "; ".join(f"{k} → {x.vendor_code} ({x.legal_name})" for k, x in dups.items()) or "No existing vendor with this PAN, GSTIN or bank account"
    st.add(Check("I2", INFO, name="Duplicate search: vendor master looked up by PAN, GSTIN and bank account before any record is created", found=found, mode="computed", source="Vendor master"))
    return f"Version {st.version.number} opened · {n} file{'s' if n != 1 else ''} stored · {found}"


# ============ 2. READ ============

def terms_days(text) -> int | None:
    """'Net 45', '45 days', '45' -> 45. Anything without a number (e.g. 'as agreed') is not a usable term."""
    m = re.search(r"\d+", str(text or ""))
    return int(m.group(0)) if m else None


def _fmt_ok(field_name: str, value: str) -> bool:
    """Does a value read from pixels look structurally valid? (tax-collector GSTINs are valid reads.)"""
    val = v.clean(value)
    if field_name == "gstin":
        return v.check_gstin(val).code in ("", "sandbox", "tax_collector", "tax_deductor", "reg_type")
    if field_name == "pan":
        return v.check_pan(val).ok
    if field_name == "cin":
        return bool(v.CIN_RE.match(val))
    if field_name == "ifsc":
        return v.check_ifsc_format(val).ok
    if field_name == "bank_account":
        return bool(v.ACCOUNT_RE.match(val)) or cn.iban_ok(val)
    if field_name == "tax_id":
        return bool(re.fullmatch(r"[A-Z0-9]{6,20}", cn.flat(val)))
    if field_name == "iban":
        return cn.iban_ok(val)
    return True


def _item_value(st, key: str) -> tuple[str, str]:
    """The number of an extra item: what the vendor typed, else what a document carries. Returns (value, 'typed' | 'document' | '')."""
    typed = (st.typed.get("x_" + key) or "").strip()
    if typed:
        return typed, "typed"
    doc = next((s_.values["x_" + key] for s_ in st.sources if s_.values.get("x_" + key)), "")
    return (doc, "document") if doc else ("", "")


def _is_low(fld: str, c: dict, floor: float = 0.0) -> bool:
    """Is this value read from pixels NOT trustworthy? Needs: the page read at or above the confidence minimum (policy), no '?', a well-formed
    value, and (when a second read exists) an identical second read. A second read that saw nothing is tolerated only for fields with a strong format check."""
    r1, r2 = c["value"], c["second"]
    if c.get("conf") is not None and c["conf"] < floor:
        return True
    if "?" in r1 or not _fmt_ok(fld, r1):
        return True
    if r2 is None:
        return False
    if r2 and ("?" in r2 or v.clean(r1) != v.clean(r2)):
        return True
    return not r2 and fld not in ("gstin", "ifsc", "cin")


def _looks(fld: str, val: str) -> str:
    """For a tax ID that differs between sources, say what kind of ID each one looks like (an Indian GSTIN, a US EIN...)."""
    if fld != "tax_id":
        return ""
    strong = [m for m in cn.detect(val) if m.strong]
    return f" (looks like {cn.describe(strong[0])})" if strong else ""


def _second(crit: dict, page: int, fld: str):
    """The independent second read of a critical field on one page. None = no second read was made."""
    if not crit:
        return None
    if any(isinstance(x, dict) for x in crit.values()):        # per-page shape
        return (crit.get(str(page)) or {}).get(fld, "")
    return crit.get(fld)                                        # flat shape (single-page files)


MATRIX_FIELD = {"legal_name": "legal_name", "pan": "pan", "gstin": "gstin", "cin": "cin", "bank_account": "bank_account", "ifsc": "ifsc",
                "account_holder": "account_holder", "new_name": "legal_name", "address": "address", "tax_id": "tax_id", "iban": "bank_account"}


BANK_DOCS = {"bank_details_form", "cancelled_cheque_or_bank_letter"}


def build_doc_map(st: RunState, foreign: dict, floor_pct: int = 0) -> list:
    """Page-by-page index of every uploaded file: what each page is and the key details found on it."""
    out = []
    for f in st.files:
        r = st.reads.get(f["sha256"])
        if not r:
            continue
        doc, pages = r["doc"], []
        n = max([p["page"] for p in doc["pages"]] + [x["page"] for x in doc["fields"]] or [1])
        for pg in range(1, n + 1):
            types = [p for p in doc["pages"] if p["page"] == pg]
            fields = [{"field": x["field"], "value": x["value"], "doc_type": x.get("doc_type", "")} for x in doc["fields"]
                      if x["page"] == pg and (x["field"] in ("legal_name", "pan", "gstin", "cin", "bank_account", "ifsc", "account_holder", "new_name", "previous_name")
                                              or x["field"] in extract.INFO_LABEL or x["field"].startswith("x_"))]
            confs = [p["confidence"] for p in types if p.get("confidence") is not None]
            pages.append({"page": pg, "types": [{"doc_type": p["doc_type"], "note": p.get("note", ""), "legible": p["legible"]} for p in types],
                          "conf": round(100 * min(confs)) if confs else None, "floor": floor_pct,
                          "fields": fields, "foreign": next((h for (fn, p2, dt), h in foreign.items() if fn == f["name"] and p2 == pg), "")})
        out.append({"sha": f["sha256"], "name": f["name"], "pages": pages})
    return out


def build_sources(st: RunState, cands: dict, typed: dict, floor: float = 0.0, custom_keys=frozenset(), titles=None) -> list:
    """One matrix row per document (file x document type) plus the typed form."""
    out = []
    tv = {k: typed[k] for k in ("legal_name", "pan", "gstin", "cin", "bank_account", "ifsc", "account_holder", "address") if typed.get(k)}
    tv.update({k: typed[k] for k in typed if k.startswith("x_") and typed.get(k)})        # numbers added in Settings
    if tv:
        out.append(MSource("typed", "New submission form", dict(tv)))
    groups: dict[tuple, MSource] = {}
    pages: dict[tuple, set] = {}
    # one row per page for everything except the registration form (a form is one document however many pages it spans),
    # so "page 9 says X but page 10 says Y" is visible
    for fld, cs in cands.items():
        mf = MATRIX_FIELD.get(fld) or (fld if fld.startswith("x_") else None)
        if not mf:
            continue
        for c in cs:
            if c["doc_type"] not in RECOGNISED and c["doc_type"] not in custom_keys:
                continue
            key = (c["file"], c["doc_type"], 0 if c["doc_type"] == FORM_DOC else c["page"])
            if c.get("foreign") and key not in groups:
                groups[key] = MSource(c["doc_type"], c["file"], {}, foreign=c["foreign"])
            s = groups.setdefault(key, MSource(c["doc_type"], c["file"], {}, title=(titles or {}).get(c["doc_type"], "")))
            pages.setdefault(key, set()).add(c["page"])
            low = fld in CRITICAL and c["imagey"] and _is_low(fld, c, floor)
            if mf not in s.values:
                s.values[mf] = c["value"]
                if low:
                    s.unclear.add(mf)
    for key, s in groups.items():
        if s.kind == "pan_card" and (s.values.get("pan") or "")[3:4].upper() == "P":
            s.proprietor = s.values.pop("legal_name", "")   # a proprietor's PAN card carries the PERSON's name, not the firm's: expected, not a mismatch
        s.ref = f"{key[0]} p.{','.join(map(str, sorted(pages[key])))}"
        out.append(s)
    return out


def stage_read(ctx, st: RunState) -> str:
    typed = st.typed
    floor = ctx.policy.get("read_confidence", 80) / 100      # the reading-confidence minimum (Settings)
    fmts = {d["key"]: d["format"] for d in custom_details(ctx.policy)}
    custom = [{**d, "format": fmts.get(d["key"], "")} for d in custom_docs(ctx.policy)]      # documents added in Settings (with the number they carry)
    custom_keys = {d["key"] for d in custom}
    confirmed = set(typed.get("_confirmed", []))
    cands: dict[str, list[dict]] = {}
    pages_summary = []
    unavailable = ""

    for f in st.files:
        try:
            doc = ctx.reader.read_document(f, progress=st.progress, confidence=floor, custom=custom)
        except ReaderUnavailable as e:
            unavailable = str(e)
            st.add(Check("R20", WAIT, key="R20:reader", name="Document reader reachable", owner="system", kind="retry",
                         title="retry reading the documents", mode="live", source="Document reader", reason=unavailable,
                         expected="Reader answers", found="Unreachable"))
            break
        for x in doc["fields"]:
            if x.get("doc_type") in custom_keys and x["field"] in extract.INFO_LABEL:
                st.item_details.setdefault(x["doc_type"], {}).setdefault(x["field"], x["value"])
        mine = {p["page"] for p in doc["pages"] if p["doc_type"] in custom_keys}
        if mine:        # a page that is clearly a document you added is not also a generic "other certificate", "address proof" or "tax document"
            weak = {"address_proof", "other_certificate", "tax_filing_document"}
            doc = {**doc, "pages": [p for p in doc["pages"] if not (p["page"] in mine and p["doc_type"] in weak)],
                   "fields": [x for x in doc["fields"] if not (x["page"] in mine and x.get("doc_type") in weak)]}
        n_pages = max([p["page"] for p in doc["pages"]] or [1])
        img_pages = imagey_pages(f, n_pages)          # pages whose digits must be read from pixels
        imagey = bool(img_pages)
        crit = {}
        recognised = [p for p in doc["pages"] if p["doc_type"] in RECOGNISED or p["doc_type"] in custom_keys]
        if imagey and recognised:
            try:
                crit = ctx.reader.read_critical(f, progress=st.progress)
            except ReaderUnavailable as e:
                unavailable = str(e)
        st.reads[f["sha256"]] = {"doc": doc, "critical": crit, "imagey": imagey, "name": f["name"]}
        page_type = {p["page"]: p for p in doc["pages"]}
        kinds = "; ".join(f"p.{p['page']} {p['doc_type'].replace('_', ' ')}" + (" (handwritten)" if p["handwritten"] else "")
                          + ("" if p["legible"] else " (NOT legible)") for p in doc["pages"])
        pages_summary.append(f"{f['name']}: {kinds}")

        # R04: is it a usable document, and legible?
        illegible = [p["page"] for p in recognised if not p["legible"]]
        if not recognised:
            st.add(Check("R04", FLAG, key=f"R04:{f['sha256'][:8]}", owner="vendor", kind="vendor", mode="document", source="Document reader",
                         expected="A registration form, GST/PAN/incorporation/Udyam document, cheque or exchange filing",
                         found=kinds or "nothing recognisable", title=f"ask for the right document instead of {f['name']}",
                         reason=f"No page of '{f['name']}' is a document type we can use.",
                         vendor_text=vtext("R04", file=f["name"], why="we could not recognise it as a business document"),
                         vendor_upload=True, evidence_ref=f["name"]))
        elif illegible:
            st.add(Check("R04", FLAG, key=f"R04:{f['sha256'][:8]}", owner="vendor", kind="vendor", mode="document", source="Document reader",
                         expected="Legible pages", found=kinds, title=f"ask for a clearer copy of {f['name']}",
                         reason=f"Page {', '.join(map(str, illegible))} of '{f['name']}' is not legible.",
                         vendor_text=vtext("R04", file=f["name"], why=f"page {', '.join(map(str, illegible))} is not legible"),
                         vendor_upload=True, evidence_ref=f["name"]))
        else:
            st.add(Check("R04", PASS, key=f"R04:{f['sha256'][:8]}", mode="document", source="Document reader", expected="Recognised, legible document",
                         found=kinds, reason="Document recognised and legible.", evidence_ref=f["name"]))
        for p in doc["pages"]:
            st.ev("doc_type", p["doc_type"], "Document reader", "document", f"{f['name']} p.{p['page']}", "document",
                  {"legible": p["legible"], "handwritten": p["handwritten"]})

        page_conf = {p["page"]: p["confidence"] for p in doc["pages"] if p.get("confidence") is not None}
        for x in doc["fields"]:
            if not x["value"]:
                continue
            pt = page_type.get(x["page"], {})
            cands.setdefault(x["field"], []).append({
                "value": x["value"], "file": f["name"], "sha": f["sha256"], "page": x["page"], "snippet": x["snippet"],
                "doc_type": x.get("doc_type") or pt.get("doc_type", "other"), "imagey": x["page"] in img_pages, "handwritten": pt.get("handwritten", False),
                "second": _second(crit, x["page"], x["field"]) if x["field"] in CRITICAL else None,
                "conf": page_conf.get(x["page"]),
            })
            if x["field"] in ("previous_name", "new_name"):
                continue
        # rename evidence: same file, both names present on rename-type documents
        prev = next((x for x in doc["fields"] if x["field"] == "previous_name" and x["value"]), None)
        new = next((x for x in doc["fields"] if x["field"] == "new_name" and x["value"]), None)
        if prev and new and page_type.get(new["page"], {}).get("doc_type") in RENAME_DOCS:
            st.renames.append({"previous": prev["value"], "new": new["value"], "file": f["name"], "page": new["page"],
                               "snippet": new["snippet"] or prev["snippet"], "doc_type": page_type[new["page"]]["doc_type"],
                               "effective": next((x["value"] for x in doc["fields"] if x["field"] == "effective_date"), "")})

    for k in disabled_fields(ctx.policy):              # details switched off in Settings are ignored wherever they appear
        cands.pop(k, None)
    # ---- bank documents in somebody else's name (e.g. pages 9-10 of a form template) are never the vendor's ----
    thr = ctx.policy["name_match_threshold"]
    vendor_name = typed.get("legal_name") or next((c["value"] for c in cands.get("legal_name", []) if c["doc_type"] == FORM_DOC), "")
    holders: dict[tuple, str] = {}
    for fld in ("account_holder", "legal_name"):
        for c in cands.get(fld, []):
            if c["doc_type"] in BANK_DOCS:
                holders.setdefault((c["file"], c["page"], c["doc_type"]), c["value"])
    foreign = {k: h for k, h in holders.items() if vendor_name and not (v.names_match(h, vendor_name, thr) or unit_of(h, vendor_name))}
    for fld in ("bank_account", "ifsc", "account_holder", "legal_name", "bank_name"):
        for c in cands.get(fld, []):
            if (c["file"], c["page"], c["doc_type"]) in foreign:
                c["foreign"] = foreign[(c["file"], c["page"], c["doc_type"])]
    own_bank = any(c["doc_type"] in BANK_DOCS and not c.get("foreign") for c in cands.get("bank_account", []))
    by_file: dict[str, list] = {}
    for (fn, pg, dt), h in foreign.items():
        by_file.setdefault(fn, []).append((pg, h))
    for fn, items in by_file.items():
        items.sort()
        pgs, holder = ", ".join(str(p) for p in sorted({p for p, _ in items})), items[0][1]
        common = dict(key=f"R04:foreign:{fn[:8]}", mode="document", source="Document reader", expected=f"Bank documents in the name of {vendor_name}",
                      found=f"Pages {pgs}: account holder is {holder}", evidence_ref=f"{fn} p.{pgs}")
        if own_bank:
            st.add(Check("R04", NOTE, reason=f"Pages {pgs} of '{fn}' are bank documents in the name of {holder}, not {vendor_name}. They were NOT used as the "
                         "vendor's bank details; the vendor's own bank document was found elsewhere.", **common))
        else:
            st.add(Check("R04", FLAG, owner="vendor", kind="vendor", title="send a bank document in the vendor's own name",
                         reason=f"Pages {pgs} of '{fn}' are bank documents in the name of {holder}, not {vendor_name}. They were NOT used as the vendor's bank "
                         "details, and no bank document in the vendor's own name was found.",
                         vendor_text=vtext("R04_foreign", file=fn, pages=pgs, holder=holder, vendor=vendor_name), vendor_upload=True, **common))
    st.doc_map = build_doc_map(st, foreign, round(100 * floor))
    st.sources = build_sources(st, cands, typed, floor, custom_keys, {d["key"]: d["label"] for d in custom})

    # ---- merge: typed > registration form > other documents; critical numbers must be confident ----
    profile: dict[str, Any] = {}
    for k in FIELDS:
        tv = (typed.get(k) or "").strip()
        form = [c for c in cands.get(k, []) if c["doc_type"] == FORM_DOC and not c.get("foreign")]
        other = [c for c in cands.get(k, []) if c["doc_type"] != FORM_DOC and not c.get("foreign")]
        pick = tv and {"value": tv, "side": "declared", "mode": "declared", "ref": "New submission form"}
        if k == "legal_name":      # the firm's name comes from its registrations, not from a proprietor's personal PAN card
            rank = {"gst_certificate": 0, "incorporation_or_name_change_certificate": 1, "udyam_certificate": 2, "address_proof": 3, "pan_card": 9}
            other = sorted(other, key=lambda c: rank.get(c["doc_type"], 5))
        doc_c = (form or other or [None])[0]
        if k in CONFLICT_FIELDS:
            # confidence of every document read; shaky reads never count as evidence of a conflict or a match
            low, highs = None, []
            for c in form + other:
                if c["imagey"]:
                    r1, r2 = c["value"], c["second"]
                    if _is_low(k, c, floor):
                        low = low or {"reads": [r1, r2 or ""], "ref": f"{c['file']} p.{c['page']}", "snippet": c["snippet"], "conf": c.get("conf")}
                        continue
                highs.append(c)
            # do ALL sources agree? typed form + every confidently-read document
            seen: dict[str, str] = {}
            orig: dict[str, str] = {}          # the value as written (dashes kept): its shape tells what kind of ID it is
            if tv:
                seen[v.clean(tv)] = "the form typed on the platform"
                orig[v.clean(tv)] = tv
            for c in highs:
                seen.setdefault(v.clean(c["value"]), f"{DOC_LABEL.get(c['doc_type'], c['doc_type'])} ({c['file']} p.{c['page']})")
                orig.setdefault(v.clean(c["value"]), c["value"])
            if len(seen) > 1 and k not in confirmed:
                st.unconfirmed[k] = {"reads": list(seen), "ref": "; ".join(seen.values()), "conflict": True,
                                     "where": [f"{lbl} shows {orig[val]}{_looks(k, orig[val])}" for val, lbl in seen.items()],
                                     "where_vendor": [f"{lbl} shows {v.mask(orig[val])}{_looks(k, orig[val])}" for val, lbl in seen.items()]}
                continue
            if tv:
                pass                # typed value stands; a shaky read must not contradict it
            elif low:
                st.unconfirmed[k] = {**low, "conflict": False}
                continue
        if tv:
            profile[k] = tv
            st.prov[k] = {"side": "declared", "mode": "declared", "ref": "New submission form"}
        elif doc_c:
            profile[k] = doc_c["value"]
            side = "declared" if doc_c["doc_type"] == FORM_DOC else "document"
            st.prov[k] = {"side": side, "mode": "document", "ref": f"{doc_c['file']} p.{doc_c['page']}", "snippet": doc_c["snippet"]}
        # document-sourced values (for the evidence table's Document column)
        for c in other:
            st.doc_values.setdefault(k, c["value"])
    for name in ("new_name",):
        for c in cands.get(name, []):
            st.doc_values.setdefault("legal_name", c["value"])
    profile["msme"] = (truthy(typed.get("msme")) or any(truthy(c["value"]) for c in cands.get("msme_claimed", [])) or bool(profile.get("udyam_number"))) \
        and doc_enabled(ctx.policy, "udyam_certificate")      # switched off in Settings: no MSME checks at all
    profile["bank_account_confirm"] = typed.get("bank_account_confirm")
    st.profile = profile
    # which country is the vendor in? what they claim; else what their identifiers point to (never guessed from digits alone)
    claimed = (typed.get("country") or "").strip()
    if len(claimed) > 2:
        claimed = next((code for code, nm in cn.COUNTRIES.items() if nm.lower() == claimed.lower()), claimed[:2])
    claimed = claimed.upper()
    profile["country"] = claimed or cn.infer_country({k: profile.get(k) for k in ("gstin", "pan", "cin", "ifsc", "tax_id", "iban", "bank_account")})
    st.country, st.country_inferred = profile["country"], bool(profile["country"]) and not claimed

    for k, p in st.prov.items():
        st.ev(k, profile.get(k), "New submission form" if p["mode"] == "declared" else "Document reader", p["mode"], p["ref"], p["side"],
              {"snippet": p.get("snippet", "")})

    # ---- R05: confidence ----
    if not st.files:
        st.add(Check("R05", SKIP, mode="computed", reason="No document attached: typed values are used as declared.", found="Typed form only"))
    elif unavailable:
        pass
    else:
        for k, u in st.unconfirmed.items():
            seen = v.mask(v.clean(u["reads"][-1] if u["reads"] else ""), 4) if u["reads"] else "…"
            code = "R05_conflict" if u.get("conflict") else "R05"
            where = "; ".join(u.get("where", []))
            st.add(Check("R05", FLAG, key=f"R05:{k}", owner="vendor", kind="vendor", mode="document", source="Document reader (independent reads)",
                         expected="The same value on every document" if u.get("conflict") else "Both reads identical and well-formed",
                         found=where if u.get("conflict") else "Reads differ or are unclear",
                         title=f"confirm the {LABELS[k]}", reason=f"The {LABELS[k]} is not the same everywhere: {where}."
                         if u.get("conflict") else f"The {LABELS[k]} on {u['ref']} could not be read with confidence"
                         + (f" (the page was read at {round(100 * u['conf'])}%, below the {round(100 * floor)}% minimum)" if u.get("conf") is not None and u["conf"] < floor else ""),
                         vendor_text=vtext(code, label=LABELS[k], seen=seen, where="; ".join(u.get("where_vendor", []))), vendor_fields=[k] + (["bank_account_confirm"] if k == "bank_account" else []),
                         evidence_ref=u["ref"], meta={"reads_masked": [v.mask(v.clean(r)) for r in u["reads"]]}))
        if not st.unconfirmed:
            st.add(Check("R05", PASS, mode="document", source="Document reader", expected="Confident reads",
                         found="Typed PDF text read exactly; photos and handwriting read twice and agreed" if any(r["imagey"] for r in st.reads.values()) else "Typed text read exactly",
                         reason="Every critical number (GSTIN, PAN, CIN, account, IFSC) was read with confidence."))

    n_fields = sum(1 for k in profile if profile.get(k) and k not in ("msme", "bank_account_confirm"))
    if unavailable:
        return f"Reader unavailable: {unavailable}"
    if not st.files:
        return f"No documents attached · {n_fields} typed fields used"
    vias = sorted({r["doc"].get("via", "") for r in st.reads.values() if r.get("doc")} - {""})
    how = {"ocr+rules": "local OCR and rules only, no AI"}.get(vias[0], vias[0]) if len(vias) == 1 else ", ".join(vias)
    scanned = [p["confidence"] for r in st.reads.values() if r.get("doc") for p in r["doc"]["pages"] if p.get("confidence") is not None and p["confidence"] < 1.0]
    conf = f" · lowest scanned page {round(100 * min(scanned))}% (minimum {round(100 * floor)}%)" if scanned else ""
    return (f"{len(st.files)} file{'s' if len(st.files) != 1 else ''} read ({how}) · {len(st.unconfirmed)} low-confidence{conf} · {n_fields} fields in profile")


# ============ 3. VALIDATE (offline, no API calls) ============

def stage_validate(ctx, st: RunState) -> str:
    p, pol = st.profile, ctx.policy
    unc = st.unconfirmed
    gstin, pan, cin = v.clean(p.get("gstin")), v.clean(p.get("pan")), v.clean(p.get("cin"))
    acct = (p.get("bank_account") or "").replace(" ", "")
    ifsc = v.clean(p.get("ifsc"))
    name = p.get("legal_name", "")
    country = st.country
    india = country == "IN"
    cname = cn.name_of(country)
    tax_id = cn.flat(p.get("tax_id"))
    given = {"GSTIN": gstin, "PAN": pan, "CIN": cin, "tax ID": (p.get("tax_id") or "").strip()}          # what the vendor actually supplied (dashes matter: 12-3456789 is an EIN)
    f_iban, f_swift, f_routing = cn.flat(p.get("iban")), cn.flat(p.get("swift")), re.sub(r"[\s\-]", "", p.get("routing_code") or "")
    if not india:
        gstin = pan = cin = ifsc = ""          # India-only rules do not apply; R23 judges any Indian ID that was given
        acct = f_iban or acct

    # R03 required items
    missing, mfields = [], []
    if not name and "legal_name" not in unc: missing.append("your legal business name"); mfields += ["legal_name"]
    if not country: missing.append("the country you are based in"); mfields += ["country"]
    if india:
        if (detail_on(pol, "gstin") or detail_on(pol, "pan")) and not (gstin or pan or "gstin" in unc or "pan" in unc): missing.append("your GSTIN or PAN"); mfields += ["gstin", "pan"]
        if detail_on(pol, "bank") and not ((acct or "bank_account" in unc) and (ifsc or "ifsc" in unc)): missing.append("your bank account number and IFSC"); mfields += ["bank_account", "bank_account_confirm", "ifsc"]
    elif country:
        if not (tax_id or given["GSTIN"] or given["PAN"] or given["CIN"] or "tax_id" in unc): missing.append(f"your tax ID ({cn.EXAMPLE.get(country, 'tax registration number')})"); mfields += ["tax_id"]
        if detail_on(pol, "bank") and not (acct or "bank_account" in unc or "iban" in unc): missing.append("your bank account (the IBAN, if your country uses one)"); mfields += ["iban", "bank_account", "routing_code", "swift"]
    if not (p.get("contact_name") and (p.get("contact_email") or p.get("contact_phone"))): missing.append("a contact name with an email or phone"); mfields += ["contact_name", "contact_email", "contact_phone"]
    cdet = [d for d in custom_details(pol) if applies_to(d, country)]                  # details added in Settings
    for d in cdet:
        if d["required"] and not _item_value(st, d["key"])[0]:                    # given on the form, or printed on a document
            missing.append(f"your {d['label']}"); mfields.append("x_" + d["key"])
    if missing:
        st.add(Check("R03", FLAG, owner="vendor", kind="vendor", mode="declared", source="Submission", expected="Legal name, country, tax ID, bank details, contact",
                     found="Missing: " + "; ".join(missing), title="send the missing details", reason="Required details are missing: " + ", ".join(missing) + ".",
                     vendor_text=vtext("R03", missing=", ".join(missing)), vendor_fields=mfields))
    else:
        st.add(Check("R03", PASS, mode="declared", source="Submission", expected="All required details", found="All present",
                     reason="Legal name, country, tax ID, bank details and a contact are present."))

    for d in cdet:                                                                      # format check of each detail you added
        (val, src), key = _item_value(st, d["key"]), "x_" + d["key"]
        if not val:
            continue
        if format_ok(d["format"], val):
            st.add(Check("X3", PASS, key=f"X3:{d['key']}", name=f"{d['label']} format", mode="computed", source="Offline check", expected=f"Format {d['format']}", found=val,
                         reason=f"The {d['label']} is in the expected format." + (" (Read from the document.)" if src == "document" else "")))
        else:
            st.add(Check("X3", FLAG, key=f"X3:{d['key']}", name=f"{d['label']} format", owner="vendor", kind="vendor", mode="computed", source="Offline check",
                         expected=f"Format {d['format']} (A letter, 9 digit, * either)", found=v.mask(val), title=f"send a valid {d['label']}",
                         reason=f"The {d['label']} is not in the expected format.", vendor_fields=[key],
                         vendor_text=f"The {d['label']} you sent ({v.mask(val)}) is not in the expected format. Please check it and send the correct one."))
    # R23: does each tax ID belong to the country the vendor claims? Shape and checksum only; never a register lookup.
    checked, bad23 = [], None
    for label, val in given.items():
        if not val or not country or (india and label in ("GSTIN", "PAN", "CIN")):
            continue
        r = cn.check_tax_id(country, val)
        if r.ok:
            checked.append(f"the {label} is a valid {cname} {r.id_type}")
        else:
            bad23 = (label, val, r)
            break
    if bad23:
        label, val, r = bad23
        tmpl = {"wrong_country": "R23_wrong_country", "invalid": "R23_invalid", "unrecognised": "R23_unrecognised", "personal": "R23_personal"}[r.code]
        found_txt = cn.describe(r.found[0]) if r.found else ""
        st.add(Check("R23", FLAG, owner="vendor", kind="vendor", mode="computed", source="Offline check", expected=f"A valid {cname} tax ID ({cn.EXAMPLE.get(country, 'local tax ID')})",
                     found=f"{label}: {val}" + (f" · looks like {found_txt}" if found_txt else ""), title=f"send a {cname} tax ID",
                     reason=r.message + " Other countries' IDs are never checked against Indian sources.",
                     vendor_text=vtext(tmpl, id=v.mask(val), found=found_txt, claimed=cname, example=cn.EXAMPLE.get(country, "your local tax ID"), type=r.id_type),
                     vendor_fields=["country", "tax_id"], meta={"claimed": country, "found": [m.country for m in r.found]}))
        st.blocked.add("tax_id")
        if not india:
            st.blocked.update({"gstin", "pan"})
    elif checked:
        st.add(Check("R23", PASS, mode="computed", source="Offline check", expected=f"A valid {cname} tax ID", found="; ".join(checked),
                     reason="; ".join(checked).capitalize() + ". This is a format and check-digit test only: there is no automatic register to confirm it exists."
                     + (" (Country inferred from the ID.)" if st.country_inferred else "")))
    elif india and any((cn.detect(x) or [cn.Match("", "")])[0].country == "IN" for x in (gstin, pan) if x):
        st.add(Check("R23", PASS, mode="computed", source="Offline check", expected="Indian tax IDs for an Indian vendor", found="GSTIN/PAN are Indian IDs",
                     reason="The tax IDs given are Indian and the vendor is based in India." + (" (Country inferred from the IDs.)" if st.country_inferred else "")))
    elif country and not india:
        st.add(Check("R23", SKIP, reason="No tax ID given yet."))

    # R06 GSTIN
    if gstin:
        r = v.check_gstin(gstin)
        sandbox = r.code == "sandbox"
        if r.ok:
            st.add(Check("R06", PASS, mode="computed", source="Offline check", expected="15 characters, valid check digit, 14th = Z",
                         found=gstin, reason="Sandbox sample GSTIN (state 00), allowed only for the connectivity test." if sandbox else
                         "Format and check digit are valid; the 14th character is Z (regular registration)."))
            st.ev("gstin.format", "valid", "Offline check", "computed", "R06")
        else:
            tmpl = {"format": "R06_format", "state": "R06_format", "shape": "R06_format", "check_digit": "R06_check_digit",
                    "tax_collector": "R06_tax_collector", "tax_deductor": "R06_tax_deductor"}.get(r.code, "R06_other")
            st.add(Check("R06", FLAG, owner="vendor", kind="vendor", mode="computed", source="Offline check",
                         expected="15 characters, valid check digit, 14th = Z", found=gstin, title="send a regular GSTIN",
                         reason=r.message + (" No API credit was spent." if r.code in ("tax_collector", "tax_deductor", "check_digit") else ""),
                         vendor_text=vtext(tmpl, gstin=v.mask(gstin)), vendor_fields=["gstin"], meta={"code": r.code}))
            st.blocked.add("gstin")
    else:
        st.add(Check("R06", SKIP, reason="No GSTIN given" if "gstin" not in unc else "GSTIN awaiting vendor confirmation."))
        if "gstin" in unc:
            st.blocked.add("gstin")

    # R07 PAN
    if pan:
        r = v.check_pan(pan)
        r2 = v.check_pan_constitution(pan, name, cin) if r.ok else r
        if r2.ok:
            st.add(Check("R07", PASS, mode="computed", source="Offline check", expected="Valid format; 4th letter fits holder type",
                         found=f"{pan} · 4th letter {pan[3]} = {v.pan_type(pan)}", reason="Format is valid and the holder type fits the vendor."))
        else:
            st.add(Check("R07", FLAG, owner="vendor", kind="vendor", mode="computed", source="Offline check", expected="Valid PAN fitting the vendor type",
                         found=pan, title="send the correct PAN", reason=r2.message, vendor_text=vtext("R07", pan=v.mask(pan)), vendor_fields=["pan"]))
            st.blocked.add("pan")
    else:
        st.add(Check("R07", SKIP, reason="No PAN given: it will be taken from the GSTIN." if gstin and "gstin" not in st.blocked else "No PAN given."))
        if "pan" in unc:
            st.blocked.add("pan")

    # R08 PAN inside GSTIN
    if gstin and "gstin" not in st.blocked and pan and "pan" not in st.blocked:
        inner = v.pan_from_gstin(gstin)
        if inner == pan:
            st.add(Check("R08", PASS, mode="computed", source="Offline check", expected=f"PAN inside GSTIN = PAN given ({pan})", found=inner,
                         reason="The PAN embedded in the GSTIN is the same as the PAN given."))
            st.ev("pan.in_gstin", inner, "Offline check", "computed", "R08")
        else:
            st.add(Check("R08", FLAG, owner="vendor", kind="vendor", mode="computed", source="Offline check",
                         expected=f"PAN given: {pan}", found=f"PAN inside GSTIN: {inner}", title="resolve the tax identity conflict",
                         reason="Tax identity conflict: the PAN inside the GSTIN differs from the PAN given. Names may look similar, but identifiers always outrank names.",
                         vendor_text=vtext("R08", gstin_pan=inner[-4:], pan=pan[-4:]), vendor_fields=["gstin", "pan"]))
            st.blocked.update({"gstin", "pan"})
    elif gstin and "gstin" not in st.blocked and not pan:
        st.derived_pan = v.pan_from_gstin(gstin)
        st.add(Check("R08", SKIP, reason=f"No PAN given; the PAN inside the GSTIN ({st.derived_pan}) will be used."))
    else:
        st.add(Check("R08", SKIP, reason="Needs a valid GSTIN and a valid PAN."))

    # R09 bank account + IFSC (India) / IBAN, routing, SWIFT (elsewhere)
    if not india:
        if not country or not (acct or "bank_account" in unc or "iban" in unc):
            st.add(Check("R09", SKIP, reason="Bank details are not available yet."))
            st.blocked.add("bank")
        else:
            issues = cn.check_foreign_bank(country, p.get("bank_account") or "", p.get("iban") or "", p.get("routing_code") or "", p.get("swift") or "")
            if issues:
                st.add(Check("R09", FLAG, key="R09:bank", owner="vendor", kind="vendor", mode="computed", source="Offline check (IBAN / routing / SWIFT)",
                             expected=f"Bank details well-formed and consistent with {cname}", found="; ".join(i.message for i in issues)[:160], title="correct the bank details",
                             reason=" ".join(i.message for i in issues), vendor_text=vtext("R09_foreign", issues=" ".join(i.message for i in issues)),
                             vendor_fields=sorted({i.field for i in issues} | ({"bank_account"} if "iban" in {i.field for i in issues} else set()))))
                st.blocked.add("bank")
            else:
                st.add(Check("R09", PASS, mode="computed", source="Offline check (IBAN / routing / SWIFT)", expected=f"Bank details consistent with {cname}",
                             found=(f"IBAN {f_iban}" if f_iban else f"Account {acct}") + (f" · SWIFT {f_swift}" if f_swift else ""),
                             reason="The bank details are well-formed (check digits) and consistent with the vendor's country. This does not prove the account exists."))
    elif acct and ifsc:
        conf = p.get("bank_account_confirm")
        ra = v.check_account(acct, conf if conf is not None and conf != "" else None)
        rf = v.check_ifsc_format(ifsc)
        if not ra.ok:
            st.add(Check("R09", FLAG, key="R09:account", owner="vendor", kind="vendor", mode="computed", source="Offline check", expected="9-18 digits, equal to its confirmation",
                         found=v.mask(acct), title="re-enter the bank account number", reason=ra.message,
                         vendor_text=vtext("R09_account", account=v.mask(acct)), vendor_fields=["bank_account", "bank_account_confirm"]))
            st.blocked.add("bank")
        elif not rf.ok:
            st.add(Check("R09", FLAG, key="R09:ifsc", owner="vendor", kind="vendor", mode="computed", source="Offline check", expected="IFSC format AAAA0XXXXXX",
                         found=ifsc, title="send the correct IFSC", reason=rf.message, vendor_text=vtext("R09_ifsc", ifsc=ifsc), vendor_fields=["ifsc"]))
            st.blocked.add("bank")
        else:
            res = ctx.ifsc.lookup(ifsc)
            if res.ok:
                st.add(Check("R09", PASS, mode="dataset", source=res.source, expected="Account is 9-18 digits; IFSC exists in the RBI list",
                             found=f"{res.fields['bank_name']} · {ifsc}", reason="Account number format is valid and the IFSC exists.", evidence_ref=res.ref))
                st.ev("ifsc.bank", res.fields["bank_name"], res.source, "dataset", res.ref, "government")
            elif res.error == "not_found":
                st.add(Check("R09", FLAG, key="R09:ifsc", owner="vendor", kind="vendor", mode="dataset", source=res.source, expected="IFSC in the RBI list",
                             found=ifsc, title="send the correct IFSC", reason=res.message, vendor_text=vtext("R09_ifsc", ifsc=ifsc), vendor_fields=["ifsc"]))
                st.blocked.add("bank")
            else:
                st.add(Check("R20", WAIT, key="R20:ifsc", owner="system", kind="retry", mode="dataset", source=res.source, name="Source reachable (IFSC dataset)",
                             title="install the IFSC dataset", reason=res.message))
                st.blocked.add("bank")
    else:
        st.add(Check("R09", SKIP, reason="Bank account or IFSC not available yet."))
        st.blocked.add("bank")

    # R10 CIN
    if cin:
        r = v.check_cin(cin, name)
        if r.ok:
            st.add(Check("R10", PASS, mode="computed", source="Offline check", expected="Valid CIN; class fits the name", found=cin,
                         reason="Format is valid and the company class fits the name."))
        else:
            st.add(Check("R10", FLAG, owner="vendor", kind="vendor", mode="computed", source="Offline check", expected="Valid CIN", found=cin,
                         title="send the correct CIN", reason=r.message, vendor_text=vtext("R10", cin=v.mask(cin)), vendor_fields=["cin"]))
            st.blocked.add("cin")
    else:
        st.add(Check("R10", SKIP, reason="No CIN: not a registered company, or none given."))

    # R17 format part
    if p.get("msme") and india:
        ud = v.clean_udyam(p.get("udyam_number"))
        if not v.check_udyam(ud).ok:
            st.add(Check("R17", FLAG, key="R17:format", owner="vendor", kind="vendor", mode="computed", source="Offline check", expected="UDYAM-XX-00-0000000",
                         found=ud or "(none)", title="send a valid Udyam number", reason="MSME was claimed but the Udyam number is missing or malformed.",
                         vendor_text=vtext("R17", udyam=v.mask(ud) or "none"), vendor_fields=["udyam_number"]))
            st.blocked.add("udyam")

    # R19 blocklist
    bl = ctx.policy.get("blocklist", {})
    used_pan = (pan or st.derived_pan) if india else vm.identity_key(p)
    if (used_pan and used_pan in [x.upper() for x in bl.get("pans", [])]) or (acct and acct in bl.get("accounts", [])):
        st.add(Check("R19", REJECT, owner="system", mode="declared", source="policy.yaml", expected="Not on the blocklist", found="On the internal blocklist",
                     reason="PAN or account is on the internal blocklist. The vendor is not told why.", vendor_text=""))
    else:
        st.add(Check("R19", PASS, mode="declared", source="policy.yaml", expected="Not on the blocklist", found="Not listed", reason="Neither the PAN nor the account is blocklisted."))

    # R01 / R02 / R18 against the vendor master (offline, local DB)
    with Session(ctx.engine) as s:
        m, on = vm.find_matches(s, used_pan, gstin if "gstin" not in st.blocked else "", "")
        others = vm.accounts_of_other_pans(s, acct, used_pan) if acct else []
    st.master, st.matched_on = m, on
    with Session(ctx.engine) as s2:
        dups = vm.search_duplicates(s2, used_pan, gstin if "gstin" not in st.blocked else "", acct)
    if len({x.vendor_code for x in dups.values()}) > 1:
        st.add(Check("R01", FLAG, key="R01:dup", owner="procurement", kind="confirm", mode="computed", source="Vendor master",
                     expected="One existing vendor, or none", found="; ".join(f"{k} → {x.vendor_code} ({x.legal_name})" for k, x in dups.items()),
                     title="resolve a possible duplicate vendor: the identifiers match different vendors",
                     reason="The PAN / GSTIN / bank account match more than one existing vendor, so creating or updating a record could duplicate or merge vendors."))
    if m and m.status == "blocked":
        st.add(Check("R01", REJECT, owner="system", mode="computed", source="Vendor master", found=f"{m.vendor_code} is blocked", reason="This vendor is blocked in the vendor master."))
    elif m:
        score = v.name_score(name, m.legal_name) if name else 100
        known_rename = any(v.names_match(r["previous"], m.legal_name, 85) or v.names_match(r["new"], m.legal_name, 85) for r in st.renames)
        if name and score < ctx.policy["name_match_threshold"] and not known_rename:
            st.add(Check("R01", FLAG, owner="procurement", kind="confirm", mode="computed", source="Vendor master", expected=f"Same name as {m.vendor_code}",
                         found=f"{m.legal_name} vs {name}", title=f"confirm this is the same vendor as {m.vendor_code}",
                         reason=f"The PAN/GSTIN match {m.vendor_code}, but the legal name differs ({score:.0f}% similar)."))
        else:
            st.add(Check("R01", NOTE, mode="computed", source="Vendor master", expected="New vendor or a clear update", found=f"{m.vendor_code} (matched on {' and '.join(on)})",
                         reason=f"Already in the vendor master as {m.vendor_code}: treated as an update to that vendor, not a new one."))
    else:
        st.add(Check("R01", PASS, mode="computed", source="Vendor master", expected="New vendor", found="No existing vendor with this PAN or GSTIN",
                     reason="No vendor master record has this PAN or GSTIN."))
    if others:
        st.add(Check("R02", FLAG, owner="finance", kind="confirm", mode="computed", source="Vendor master", expected="Account used by one PAN only",
                     found="Already used by a different PAN", title="review a bank account already used by another vendor",
                     reason="This bank account is already registered to a different PAN in the vendor master. This is never shown to the vendor.", vendor_text=""))
    else:
        st.add(Check("R02", PASS if acct else SKIP, mode="computed", source="Vendor master", expected="Account not used by a different PAN",
                     found="No conflict" if acct else "", reason="No other PAN uses this bank account." if acct else "No account yet."))
    active = vm.active_bank(m) if m else None
    if m and active and acct and "bank" not in st.blocked and (acct != active["account"] or (ifsc if india else f_swift) != active["ifsc"]):
        c = m.record.get("contact_on_file", {})
        st.add(Check("R18", FLAG, owner="finance", kind="confirm", requirement="bank_account", mode="computed", source="Vendor master",
                     expected=f"Approved account {v.mask(active['account'])} · {active['ifsc']}", found=f"New account {v.mask(acct)} · {ifsc}",
                     title="verify the new bank account with the contact on file",
                     detail=f"Confirm through the contact on file ({c.get('name', '')}, {v.mask(c.get('phone', ''))} / {c.get('email', '')}), "
                            "never the contact in this submission. Two approvers are required.",
                     reason=f"Bank details differ from the approved ones on {m.vendor_code}. The approved account stays active until this is confirmed."))
    elif m and active and acct and "bank" not in st.blocked:
        st.add(Check("R18", PASS, mode="computed", source="Vendor master", expected="Same bank details as approved", found="Unchanged",
                     reason=f"Bank details are the same as the approved account on {m.vendor_code}."))
    else:
        st.add(Check("R18", SKIP, reason="No approved vendor with a bank account to compare against."))
    # R27 / R28: internal classification and payment terms. Procurement enters these; the terms must equal what was negotiated.
    if pol.get("require_commercial_setup", True):
        miss = [lbl for k, lbl in (("vendor_type", "goods or services"), ("expense_category", "expense category"), ("department_owner", "department owner")) if not p.get(k)]
        if miss:
            st.add(Check("R27", FLAG, owner="procurement", kind="categorise", mode="declared", source="Procurement", expected="Goods/services, expense category, department owner",
                         found="Missing: " + ", ".join(miss), title="categorise the vendor (goods or services, expense category, department owner)",
                         reason="The vendor has not been categorised yet: " + ", ".join(miss) + "."))
        else:
            st.add(Check("R27", PASS, mode="declared", source="Procurement", expected="Categorised", found=f"{p['vendor_type']} · {p['expense_category']} · owner: {p['department_owner']}",
                         reason="Goods vs services, expense category and department owner are set."))
        nd, sd = terms_days(p.get("negotiated_terms")), terms_days(p.get("system_terms"))
        if nd is None or sd is None:
            st.add(Check("R28", FLAG, owner="procurement", kind="categorise", mode="declared", source="Procurement", expected="Negotiated terms and configured terms, both in days",
                         found=f"negotiated: {p.get('negotiated_terms') or '—'}; configured: {p.get('system_terms') or '—'}", title="enter the negotiated and the configured payment terms",
                         reason="Payment terms are not complete: both the negotiated commercial terms and the terms configured in the system are needed (in days, e.g. 45 or 'Net 45')."))
        elif nd != sd:
            st.add(Check("R28", FLAG, owner="procurement", kind="categorise", mode="declared", source="Procurement", expected=f"Configured terms = negotiated terms ({nd} days)",
                         found=f"configured {sd} days ≠ negotiated {nd} days", title="make the configured payment terms match the negotiated terms",
                         reason=f"The payment terms configured in the system ({sd} days) do not match the negotiated commercial terms ({nd} days). They must match exactly."))
        elif p.get("msme") and sd > pol.get("msme_payment_terms_days", 45):
            st.add(Check("R28", FLAG, owner="procurement", kind="categorise", mode="declared", source="Procurement", expected=f"At most {pol.get('msme_payment_terms_days', 45)} days for an MSME",
                         found=f"{sd} days", title="shorten the payment terms (MSME vendor)", reason=f"The vendor claims MSME status; payment terms above {pol.get('msme_payment_terms_days', 45)} days are not allowed for micro and small enterprises."))
        else:
            st.add(Check("R28", PASS, mode="declared", source="Procurement", expected="Configured terms = negotiated terms", found=f"{sd} days = {nd} days",
                         reason=f"The payment terms configured in the system ({sd} days) match the negotiated terms exactly."))
    if not india:
        for c in st.checks["validate"]:
            if c.rule in ("R06", "R07", "R08", "R10") and c.result == SKIP:
                c.reason = f"Not applicable: the vendor is based in {cname}, so Indian tax IDs are not used."
    bad = sum(1 for c in st.checks["validate"] if c.blocking or c.result == REJECT)
    return "All offline checks passed" if not bad else f"{bad} flagged — API calls skipped for failed identifiers"


# ============ 4. VERIFY ============

def _assisted_gst(st: RunState, gstin: str) -> AdapterResult | None:
    for e in st.assisted.get("gst", []):
        if v.clean(e["meta"].get("identifier")) == gstin:
            f = e["meta"]["fields"]
            code = gstin[:2]
            fields = {"gstin": gstin, "legal_name": f.get("legal_name", ""), "trade_name": f.get("trade_name", ""), "status": f.get("status", ""),
                      "taxpayer_type": f.get("taxpayer_type", ""), "constitution": f.get("constitution", ""),
                      "registration_date": f.get("registration_date", ""), "cancellation_date": f.get("cancellation_date", ""),
                      "state_code": code, "state": v.STATES.get(code, ""), "einvoice_status": "", "address": "", "pincode": ""}
            return AdapterResult(True, fields, "GST portal (reviewer-checked)", "assisted", ref=f"screenshot {e['meta'].get('screenshot', '')[:8]} · {e['captured_by']} · approved by {e['approved_by']}")
    return None


def _pan_api(st: RunState, pan: str):
    return next((e for e in st.assisted.get("pan_api", []) if v.clean(e["meta"].get("identifier")) == v.clean(pan)), None)


def _r14_from_api(ctx, st: RunState, pan: str) -> None:
    """R14 from a live PAN verify (gstinapi.in): the PAN exists and has a registered holder name and status."""
    e = _pan_api(st, pan)
    f, meta = e["meta"]["fields"], e["meta"]
    nm, status = f.get("name", ""), (f.get("status") or "").lower()
    declared, thr = st.profile.get("legal_name", ""), ctx.policy["name_match_threshold"]
    ref = f"gstinapi.in PAN verify · {meta.get('fetched_at', '')[:19].replace('T', ' ')}"
    score = v.name_score(nm, declared) if declared else 100.0
    st.ev("pan.registered_name", nm, "gstinapi.in PAN verify", "live", ref, "government")
    st.ev("pan.status", f.get("status", ""), "gstinapi.in PAN verify", "live", ref, "government")
    common = dict(mode="live", source="gstinapi.in PAN verify", evidence_ref=ref, expected="PAN exists, active, holder name agrees", found=f"{nm or '(no name)'} · {f.get('status') or 'status n/a'}")
    if any(w in status for w in ("fake", "delet", "deactiv", "invalid")) or f.get("verified") is False:
        st.add(Check("R14", REJECT, reason=f"The PAN is reported as '{f.get('status') or 'not verified'}' by the PAN source.", **common))
    elif "inoperative" in status:
        st.add(Check("R14", FLAG, owner="vendor", kind="vendor", title="link the PAN to Aadhaar (it is inoperative)", vendor_text=vtext("R14_inoperative"),
                     reason="The PAN is inoperative. A higher TDS rate applies until it is linked to Aadhaar.", condition="PAN inoperative: higher TDS rate applies.",
                     recheck_days=ctx.policy["recheck_days"]["advisory"], **common))
    elif declared and score < thr and (st.profile.get("pan") or st.derived_pan)[3:4] != "P":
        st.add(Check("R14", FLAG, key="R14:name", owner="procurement", kind="confirm", title="review the PAN holder's registered name",
                     reason=f"The PAN is registered to '{nm}', but the declared legal name is '{declared}' ({score:.0f}% similar).", **common))
    else:
        st.add(Check("R14", PASS, requirement="pan_identity", reason=f"PAN verified live: registered to '{nm}', status {f.get('status') or 'active'}."
                     + (" (A proprietor's PAN is held in the person's name.)" if declared and score < thr else ""), **common))


def _pending_assist(st: RunState, rule: str, source: str, ident: str, title: str, reason: str, owner="procurement", requirement="", **kw) -> Check:
    return st.add(Check(rule, WAIT, owner=owner, kind="evidence", assist=source, requirement=requirement, mode="", title=title, reason=reason,
                        expected="Evidence from an accepted source", found="Not yet checked", meta={"identifier": ident}, **kw))


def _verify_foreign(ctx, st: RunState) -> str:
    """A vendor outside India: no Indian source applies, and there is no register we can query for its tax ID. So the tax ID
    is checked by a person on the official site (assisted evidence, approved by a second person) and the bank account by finance."""
    p = st.profile
    c, cname = st.country, cn.name_of(st.country)
    for rule in ("R11", "R13", "R14", "R15", "R17", "R21"):
        st.add(Check(rule, SKIP, reason=f"Not applicable: the vendor is based in {cname}; this source covers Indian registrations only. No Indian API was called."))
    tax = cn.flat(p.get("tax_id"))
    if c and tax and "tax_id" not in st.blocked:
        a = next((e for e in st.assisted.get("taxid", []) if cn.flat(e["meta"].get("identifier")) == tax), None)
        site = cn.SITES.get(c, ("the tax authority's online register", ""))
        if a:
            f = a["meta"]["fields"]
            status = (f.get("status") or "").lower()
            ref = f"screenshot {a['meta'].get('screenshot', '')[:8]} · {a['captured_by']} · approved by {a['approved_by']}"
            if any(w in status for w in ("invalid", "not found", "inactive", "cancel", "revok", "terminat", "deregist", "no match")):
                st.add(Check("R23", FLAG, key="R23v", owner="vendor", kind="vendor", requirement="tax_registration", mode="assisted", source=f"{site[0]} (reviewer-checked)",
                             expected="Registered", found=f.get("status") or "not found", title="send a valid tax ID", vendor_fields=["tax_id"], evidence_ref=ref,
                             reason="The official register did not confirm this tax ID.", vendor_text=vtext("R23_notfound", id=v.mask(tax), claimed=cname)))
            else:
                st.add(Check("R23", PASS, key="R23v", requirement="tax_registration", mode="assisted", source=f"{site[0]} (reviewer-checked)", expected="Registered",
                             found=f.get("status") or "confirmed", reason="A reviewer confirmed this tax ID on the official register (screenshot kept).", evidence_ref=ref))
        else:
            st.add(Check("R23", WAIT, key="R23v", owner="procurement", kind="evidence", assist="taxid", requirement="tax_registration", mode="",
                         source="Official register (manual)", expected="Tax ID confirmed on the official register", found="Not checked yet",
                         title=f"verify the tax ID on the official {cname} register",
                         reason=f"There is no automatic lookup for {cname}. The ID's format is valid, but a person must confirm it exists and is active: {site[0]}.",
                         meta={"identifier": tax, "country": c}))
    elif c and not tax:
        st.add(Check("R23", SKIP, key="R23v", reason="No tax ID to verify yet."))
    acct = cn.flat(p.get("iban")) or (p.get("bank_account") or "").replace(" ", "")
    if acct and "bank" not in st.blocked:
        m = st.master
        active = vm.active_bank(m) if m else None
        if flagged(st, "R18"):
            st.add(Check("R16", SKIP, reason="Covered by the bank-change check: confirmed through the contact on file."))
        elif active and active["account"] == acct:
            st.add(Check("R16", PASS, requirement="bank_account", mode=active.get("mode", "assisted"), source="Vendor master (verified earlier)",
                         expected="Account verified", found=f"{acct} verified {active.get('at', '')[:10]}", reason=f"Same account already verified for {m.vendor_code}; the verification is carried forward.",
                         meta={"bank_confirmation": {"carried": True, **{k: active.get(k, "") for k in ('verified_via', 'verified_by', 'approved_by', 'mode')}}}))
        else:
            st.add(Check("R16", WAIT, owner="finance", kind="confirm", requirement="bank_account", mode="", source="Finance confirmation (two people)",
                         expected="Account confirmed by finance and approved by a second person", found="No live penny drop for this country",
                         title="confirm the bank account", reason="There is no automatic bank verification outside India, so finance must confirm the account and a second person must approve.",
                         detail=f"Confirm that {acct} is active and held in the vendor's name (call the bank, or check a bank letter). Record how you confirmed it."))
    else:
        st.add(Check("R16", SKIP, reason="Bank details are not ready: waiting on earlier checks."))
    return f"{cname}: Indian sources skipped · tax ID needs a manual register check · no API credit spent"


def stage_verify(ctx, st: RunState) -> str:
    p, pol = st.profile, ctx.policy
    if st.country != "IN":
        return _verify_foreign(ctx, st)
    gstin, pan, cin = v.clean(p.get("gstin")), v.clean(p.get("pan")), v.clean(p.get("cin"))
    acct, ifsc = (p.get("bank_account") or "").replace(" ", ""), v.clean(p.get("ifsc"))
    name = p.get("legal_name", "")
    notes = []

    # ---- GST: R11, R20, R21, R14 (PAN derived from GST) ----
    if gstin and "gstin" not in st.blocked:
        res = ctx.gst.lookup(gstin)
        if res.unreachable and (alt := _assisted_gst(st, gstin)):
            res = alt
        st.gst = res
        if res.ok:
            f = res.fields
            notes.append(f"GST {f['status'] or '?'} ({res.mode}{', cached' if res.from_cache else ''})")
            for k in ("legal_name", "trade_name", "status", "taxpayer_type", "state", "registration_date", "cancellation_date", "einvoice_status"):
                st.ev(f"gst.{k}", f.get(k), res.source, res.mode, res.ref, "government")
            gref = f"{res.source} · {res.fetched_at[:19].replace('T', ' ')}" if res.mode != "assisted" else res.ref
            status = (f["status"] or "").lower()
            if status == "active":
                st.add(Check("R11", PASS, requirement="gst_registration", mode=res.mode, source=res.source, expected="Active", found=f"Active · {f['state']}",
                             reason=f"GST record is Active. Legal name on record: {f['legal_name']}.", evidence_ref=gref, meta={"gst": f}))
            elif "cancel" in status:
                st.add(Check("R11", REJECT, requirement="gst_registration", mode=res.mode, source=res.source, expected="Active",
                             found=f"Cancelled{(' on ' + f['cancellation_date']) if f['cancellation_date'] else ''}", reapply=True, vendor_fields=["gstin"],
                             reason="GST registration is cancelled. The application is rejected for this GSTIN; the vendor may apply again with an active GSTIN.",
                             vendor_text=vtext("R11_cancelled", gstin=v.mask(gstin)), evidence_ref=gref, meta={"gst": f}))
            elif "suspend" in status:
                st.add(Check("R11", FLAG, owner="vendor", kind="vendor", requirement="gst_registration", mode=res.mode, source=res.source, expected="Active",
                             found="Suspended", title="resolve the suspended GST registration or send another GSTIN", vendor_fields=["gstin"],
                             reason="GST registration is suspended.", vendor_text=vtext("R11_suspended", gstin=v.mask(gstin)), evidence_ref=gref, meta={"gst": f}))
            else:
                st.add(Check("R11", FLAG, owner="procurement", kind="confirm", requirement="gst_registration", mode=res.mode, source=res.source, expected="Active",
                             found=f["status"] or "unknown", title="review the GST status", reason=f"GST status is '{f['status']}', which needs a person to review.",
                             evidence_ref=gref, meta={"gst": f}))
            # R21 taxpayer type + e-invoicing
            tt = (f["taxpayer_type"] or "").lower()
            einv = f["einvoice_status"] or "not reported"
            if tt.startswith("regular") or tt == "":
                st.add(Check("R21", PASS if tt else INFO, mode=res.mode, source=res.source, expected="Regular taxpayer", found=f"{f['taxpayer_type'] or 'not reported'} · e-invoicing: {einv}",
                             reason=f"Regular taxpayer; e-invoicing status recorded: {einv}.", evidence_ref=gref))
            elif tt.startswith("composition"):
                st.add(Check("R21", NOTE, mode=res.mode, source=res.source, expected="Regular taxpayer", found=f"Composition · e-invoicing: {einv}",
                             reason="Composition taxpayer: passes with an accounts-payable flag, because no input tax credit can be claimed on its invoices.",
                             condition="AP flag: composition taxpayer, no input tax credit on its invoices.", recheck_days=pol["recheck_days"]["advisory"], evidence_ref=gref))
            elif tt.startswith("sez"):
                st.add(Check("R21", NOTE, mode=res.mode, source=res.source, expected="Regular taxpayer", found=f"{f['taxpayer_type']} · e-invoicing: {einv}",
                             reason=f"SEZ registration: a legitimate GST registration, recorded as '{f['taxpayer_type']}'. E-invoicing status recorded: {einv}.", evidence_ref=gref))
            else:
                st.add(Check("R21", FLAG, owner="procurement", kind="confirm", mode=res.mode, source=res.source, expected="Regular taxpayer", found=f["taxpayer_type"],
                             title="review the GST taxpayer type", reason=f"Taxpayer type '{f['taxpayer_type']}' needs procurement review.", evidence_ref=gref))
            # R14 PAN identity derived from GST
            if status == "active" and gstin and not _pan_api(st, pan or v.pan_from_gstin(gstin)):
                inner = v.pan_from_gstin(gstin)
                if not pan or pan == inner:
                    derived_ok = res.mode in ("live", "assisted")
                    st.add(Check("R14", PASS, requirement="pan_identity", mode="derived_from_gst" if derived_ok else res.mode, source=f"{res.source} (PAN inside active GSTIN)",
                                 expected="PAN valid and operative", found=f"{inner} validated by GSTN at registration",
                                 reason="GSTN validated this PAN when the GSTIN was registered, so PAN identity is derived from the active GST record.", evidence_ref=gref))
                    st.ev("pan.identity", inner, res.source, "derived_from_gst" if derived_ok else res.mode, gref, "government")
        elif res.error == "not_found":
            st.add(Check("R11", FLAG, owner="vendor", kind="vendor", requirement="gst_registration", mode=res.mode, source=res.source, expected="GSTIN registered",
                         found="Not found in GST records", title="check the GSTIN", vendor_fields=["gstin"],
                         reason="The GSTIN is well-formed but not registered in the GST database.", vendor_text=vtext("R11_missing", gstin=v.mask(gstin))))
            notes.append("GSTIN not found")
        else:   # unreachable: never a pass (R20)
            kind = {"not_configured": "not configured", "simulated_outage": "SIMULATED outage"}.get(res.error, res.error)
            st.add(Check("R20", WAIT, key="R20:gst", owner="system", kind="retry", mode=res.mode, source=res.source, name="Source reachable (GST)",
                         expected="GST source answers", found=f"Unreachable ({kind})", title="retry the GST check once the source is back",
                         reason=res.message + " The check is pending, never treated as a pass.", meta={"error": res.error}))
            st.add(Check("R11", SKIP, reason="Not checked: the GST source is unreachable."))
            notes.append(f"GST unreachable ({kind})")
    else:
        why = "GSTIN did not pass Validate" if gstin else "no GSTIN"
        st.add(Check("R11", SKIP, reason=f"Skipped, no API credit spent: {why}."))
        notes.append(f"GST skipped ({why})")
        if not gstin and pan and "pan" not in st.blocked and not _pan_api(st, pan):
            _pending_assist(st, "R14", "pan", pan, "verify the PAN on the Income Tax site", "No active GSTIN to derive PAN identity from: PAN needs an assisted check.",
                            requirement="pan_identity")

    if _pan_api(st, pan or st.derived_pan):
        _r14_from_api(ctx, st, pan or st.derived_pan)

    # ---- R13 filing history (on demand only) ----
    filings = next((e for e in st.assisted.get("filings", []) if v.clean(e["meta"].get("identifier")) == gstin), None)
    if filings:
        gap = filings["meta"].get("missing_periods", [])
        if len(gap) > pol["filing_gap_months"]:
            st.add(Check("R13", FLAG, owner="procurement", kind="confirm", mode="live", source="gstinapi.in", expected=f"At most {pol['filing_gap_months']} months missing",
                         found=f"{len(gap)} GSTR-3B months missing: {', '.join(gap[:6])}", title="review GST filing gaps (input tax credit at risk)",
                         reason="GSTR-3B returns are missing for several months, which puts input tax credit at risk."))
        else:
            st.add(Check("R13", PASS, mode="live", source="gstinapi.in", expected="No unexplained gaps", found=f"{len(gap)} month(s) missing", reason="Returns filed with no unexplained gaps."))
    else:
        st.add(Check("R13", INFO, reason="Filing history is fetched on demand (one credit): use 'Check filing history' on the case.", found="Not requested"))

    # ---- R15 company status (MCA has no free API) ----
    if cin and "cin" not in st.blocked:
        mca = next((e for e in st.assisted.get("mca", []) if v.clean(e["meta"].get("identifier")) == cin), None)
        doc_cert = any(r["doc_type"] in RENAME_DOCS for r in st.renames) or any(
            x["doc"] and any(pg["doc_type"] == "incorporation_or_name_change_certificate" for pg in x["doc"]["pages"]) for x in st.reads.values())
        days = pol["recheck_days"]["company_status"]
        if mca:
            status = (mca["meta"]["fields"].get("company_status") or "").lower()
            ref = f"screenshot {mca['meta'].get('screenshot', '')[:8]} · {mca['captured_by']} · approved by {mca['approved_by']}"
            if any(w in status for w in ("strike", "struck", "dissol", "liquidat", "amalgamat")):
                st.add(Check("R15", REJECT, requirement="company_status", mode="assisted", source="MCA (reviewer-checked)", expected="Active", found=status.title(),
                             reason="MCA shows the company is struck off, dissolved or in liquidation.", evidence_ref=ref))
            else:
                st.add(Check("R15", PASS, requirement="company_status", mode="assisted", source="MCA (reviewer-checked)", expected="Active", found=status.title() or "Active",
                             reason="Company status confirmed on the MCA site by a reviewer.", evidence_ref=ref, meta={"company_status": status.title()}))
        elif doc_cert:
            st.add(Check("R15", NOTE, requirement="company_status", mode="document", source="Government document uploaded by vendor", expected="Active on MCA",
                         found="Only a document (certificate / exchange filing) supports company status",
                         reason="Company status is supported by a document only. Approved with the condition to re-check before the first payment.",
                         condition="Re-check company status on MCA before the first payment.", recheck_days=days, meta={"company_status": "document only"}))
        else:
            st.add(Check("R15", NOTE, requirement="company_status", mode="", source="MCA", expected="Active on MCA", found="No evidence yet",
                         reason="MCA has no free API, so company status is unverified. Approved with the condition to re-check before the first payment.",
                         condition="Re-check company status on MCA before the first payment (no evidence on file).", recheck_days=days,
                         assist="mca", meta={"company_status": "not verified", "identifier": cin}))
    else:
        st.add(Check("R15", SKIP, reason="No (valid) CIN: company status does not apply or is waiting on the vendor."))

    # ---- R16 bank ----
    if acct and ifsc and "bank" not in st.blocked:
        r18_open = flagged(st, "R18")
        m = st.master
        active = vm.active_bank(m) if m else None
        if r18_open:
            st.add(Check("R16", SKIP, reason="Covered by the bank-change check: confirmed through the contact on file."))
        elif active and active["account"] == acct and active["ifsc"] == ifsc:
            st.add(Check("R16", PASS, requirement="bank_account", mode=active.get("mode", "assisted"), source="Vendor master (verified earlier)",
                         expected="Account verified", found=f"{v.mask(acct)} verified {active.get('at', '')[:10]} via {active.get('verified_via', 'finance confirmation')}",
                         reason=f"Same account already verified for {m.vendor_code}; the verification is carried forward.",
                         meta={"bank_confirmation": {"carried": True, **{k: active.get(k, "") for k in ('verified_via', 'verified_by', 'approved_by', 'mode')}}}))
        elif ctx.bav and ctx.bav.configured:
            br = ctx.bav.verify(acct, ifsc, name)
            if br.unreachable:
                st.add(Check("R20", WAIT, key="R20:bank", owner="system", kind="retry", mode=br.mode, source=br.source, name="Source reachable (bank penny drop)",
                             title="retry the bank verification", reason=br.message, found="Unreachable"))
            elif br.mode != "live":
                st.add(Check("R16", WAIT, owner="finance", kind="confirm", requirement="bank_account", mode="sandbox", source=br.source, expected="Live penny drop",
                             found="Cashfree is in sandbox mode: it only answers for its published test accounts",
                             title="confirm the bank account with a second person", reason="A sandbox answer is never used to verify a real vendor; two finance people must confirm.",
                             detail="Confirm the account holder and that the account is active (call the bank, or check a cancelled cheque). A second person approves."))
            elif br.ok and br.fields.get("valid"):
                holder = br.fields.get("name_at_bank", "")
                if holder and not v.names_match(holder, name, pol["name_match_threshold"]) and not v.names_match(holder, p.get("trade_name", ""), pol["name_match_threshold"]):
                    st.add(Check("R16", FLAG, owner="finance", kind="confirm", requirement="bank_account", mode="live", source=br.source, expected=f"Holder ≈ {name}",
                                 found=f"Holder at bank: {holder}", title="review the bank account holder name mismatch",
                                 reason="The account is active but the holder name does not match the legal name.", evidence_ref=br.ref))
                else:
                    st.add(Check("R16", PASS, requirement="bank_account", mode="live", source=br.source, expected="Active, holder matches", found=f"Active · {holder}",
                                 reason="Penny drop confirmed the account is active and the holder matches.", evidence_ref=br.ref,
                                 meta={"bank_confirmation": {"verified_via": "Cashfree penny drop", "mode": "live"}}))
                    st.ev("bank.account_holder", holder, br.source, "live", br.ref, "government")
            else:
                st.add(Check("R16", FLAG, owner="vendor", kind="vendor", requirement="bank_account", mode="live", source=br.source, expected="Active account",
                             found=br.fields.get("status_code") or br.message, title="re-check the bank account details", vendor_fields=["bank_account", "bank_account_confirm", "ifsc"],
                             reason="The bank could not confirm this account.", vendor_text=vtext("R16_invalid", account=v.mask(acct))))
        else:
            st.add(Check("R16", WAIT, owner="finance", kind="confirm", requirement="bank_account", mode="", source="Finance confirmation (two people)",
                         expected="Live penny drop, or finance confirmation approved by a second person", found="No live penny drop configured",
                         title="confirm the bank account", reason="No live penny drop is configured, so finance must confirm the account and a second person must approve.",
                         detail=f"Confirm that {v.mask(acct)} ({ifsc}) is active and held in the vendor's name (call the bank, or check a cancelled cheque). Record how you confirmed it."))
        if ctx.enrich and not ctx.sim:
            bd = ctx.ifsc.branch_details(ifsc)
            if bd:
                st.ev("ifsc.branch", f"{bd.fields['branch']}, {bd.fields['city']}", bd.source, "live", bd.ref, "government")
    else:
        st.add(Check("R16", SKIP, reason="Bank details are not ready: waiting on earlier checks."))

    # ---- R17 Udyam ----
    if p.get("msme") and "udyam" not in st.blocked:
        ud = v.clean_udyam(p.get("udyam_number"))
        a = next((e for e in st.assisted.get("udyam", []) if v.clean_udyam(e["meta"].get("identifier")) == ud), None)
        if a:
            f = a["meta"]["fields"]
            etype = (f.get("enterprise_type") or "").title()
            valid = "active" in (f.get("status") or "").lower() or "valid" in (f.get("status") or "").lower() or bool(etype)
            ref = f"screenshot {a['meta'].get('screenshot', '')[:8]} · {a['captured_by']} · approved by {a['approved_by']}"
            if valid:
                terms = pol["msme_payment_terms_days"] if etype in ("Micro", "Small") else None
                st.add(Check("R17", PASS, requirement="udyam", mode="assisted", source="Udyam (reviewer-checked)", expected="Valid Udyam", found=f"{etype or 'Valid'} enterprise",
                             reason=f"Udyam confirmed: {etype} enterprise." + (f" Payment terms of {terms} days or less apply (MSME rule)." if terms else ""),
                             evidence_ref=ref, meta={"enterprise_type": etype, "payment_terms_days": terms},
                             condition=f"MSME ({etype}): pay within {terms} days." if terms else "", recheck_days=pol["recheck_days"]["advisory"]))
            else:
                st.add(Check("R17", FLAG, owner="vendor", kind="vendor", requirement="udyam", mode="assisted", source="Udyam (reviewer-checked)", expected="Valid Udyam",
                             found=f.get("status", "invalid"), title="send a valid Udyam number", vendor_fields=["udyam_number"], reason="The Udyam registration could not be validated.",
                             vendor_text=vtext("R17", udyam=v.mask(ud)), evidence_ref=ref))
        else:
            _pending_assist(st, "R17", "udyam", ud, "verify the Udyam registration on the official site",
                            "MSME was claimed. There is no free Udyam API, so a reviewer checks the official page.", requirement="udyam")
    elif not p.get("msme"):
        st.add(Check("R17", SKIP, reason="MSME not claimed."))

    flags = sum(1 for c in st.checks.get("verify", []) if c.blocking or c.result == REJECT)
    return "; ".join(notes) + (f" · {flags} need attention" if flags else "") if notes else ("Nothing to verify yet" if not flags else f"{flags} need attention")


# ============ 5. RECONCILE ============

def stage_reconcile(ctx, st: RunState) -> str:
    p, pol = st.profile, ctx.policy
    thr = pol["name_match_threshold"]
    declared = p.get("legal_name", "")
    g = st.gst.fields if (st.gst and st.gst.ok) else None
    result_of: dict[str, str] = {}

    if not declared:
        st.add(Check("R12", SKIP, reason="No legal name declared yet."))
    elif g is None:
        st.add(Check("R12", SKIP, reason=(f"No government record is consulted for {cn.name_of(st.country)}; names are compared across the documents in the table below." if st.country != "IN"
                                else "Waiting for the GST record to compare names." if "gstin" not in st.blocked else "Skipped: no verified GST record.")))
    else:
        gl, gt = g["legal_name"], g["trade_name"]
        score = v.name_score(declared, gl)
        names_compared = [("declared name", declared), ("GST legal name", gl)]
        doc_name = st.doc_values.get("legal_name")
        if score >= thr:
            extra = ""
            if doc_name and v.name_score(doc_name, gl) < thr and not any(v.names_match(doc_name, r["previous"], thr) or v.names_match(doc_name, r["new"], thr) for r in st.renames):
                extra = f" (a document shows '{doc_name}')"
            st.add(Check("R12", PASS, mode=st.gst.mode, source=st.gst.source, expected=declared, found=gl, reason=f"Declared name matches the GST legal name ({score:.0f}% similar){extra}.",
                         evidence_ref=st.gst.ref))
            result_of["legal_name"] = "match"
        else:
            rename = next((r for r in st.renames if
                           (v.names_match(declared, r["previous"], thr) and v.names_match(gl, r["new"], thr)) or
                           (v.names_match(declared, r["new"], thr) and v.names_match(gl, r["previous"], thr))), None)
            proprietor = (p.get("pan") or st.derived_pan)[3:4] == "P" and gt and (v.names_match(declared, gt, thr) or v.names_match(gl, p.get("trade_name", ""), thr))
            if rename:
                ref = f"{rename['file']} p.{rename['page']}: “{rename['snippet']}”"
                why = (f"The declared name '{declared}' differs from the GST record '{gl}' ({score:.0f}% similar), but a "
                       f"{'stock-exchange filing' if rename['doc_type'] == 'stock_exchange_filing' else 'government name-change document'} names both: "
                       f"'{rename['previous']}' renamed to '{rename['new']}'" + (f" (effective {rename['effective']})" if rename["effective"] else "") + f". Evidence: {ref}")
                if pol["rename_requires_person"]:
                    st.add(Check("R12", FLAG, owner="procurement", kind="confirm", mode="document", source="Name-change evidence", expected=declared, found=gl,
                                 title="confirm the company name change", reason=why + " Policy requires a person to confirm every rename.", evidence_ref=ref))
                    result_of["legal_name"] = "needs review"
                else:
                    st.add(Check("R12", NOTE, mode="document", source="Name-change evidence", expected=declared, found=gl, reason=why, evidence_ref=ref))
                    result_of["legal_name"] = "explained"
            elif proprietor:
                st.add(Check("R12", NOTE, mode=st.gst.mode, source=st.gst.source, expected=declared, found=f"{gl} (trade name: {gt})",
                             reason=f"The declared name matches the GST trade name '{gt}' and the PAN is an individual/proprietor PAN: a proprietor link.", evidence_ref=st.gst.ref))
                result_of["legal_name"] = "explained"
            else:
                st.add(Check("R12", FLAG, owner="procurement", kind="confirm", mode=st.gst.mode, source=st.gst.source, expected=declared, found=gl,
                             title="review the legal-name difference", evidence_ref=st.gst.ref,
                             reason=f"The declared name and the GST legal name are only {score:.0f}% similar and no rename or proprietor link was found in the evidence.",
                             detail=f"Declared: {declared}. GST legal name: {gl}. Trade name: {gt or '—'}. Ask the vendor for the name-change certificate if this was a rename."))
                result_of["legal_name"] = "mismatch"
        if gt and p.get("trade_name"):
            result_of["trade_name"] = "match" if v.names_match(gt, p["trade_name"], thr) else "mismatch"

    # advisories: never blocking. Real vendors fail both legitimately (see Eternal).
    pan_used = v.clean(p.get("pan")) or st.derived_pan
    if pan_used and declared and pan_used[4:5] != v.normalise_name(declared)[:1]:
        st.add(Check("A1", INFO, name="Advisory: PAN 5th letter vs name initial", expected=f"Initial {v.normalise_name(declared)[:1]}", found=f"PAN 5th letter {pan_used[4]}",
                     mode="computed", source="Offline hint", reason="Often differs after a rename or for old company names. Informational only, never blocks."))
    cin = v.clean(p.get("cin"))
    if cin and g and v.CIN_RE.match(cin):
        office = v.CIN_STATES.get(cin[6:8], "")
        if office and g.get("state") and office != g["state"]:
            st.add(Check("A2", INFO, name="Advisory: GST state vs registered-office state", expected=office, found=g["state"], mode="computed", source="Offline hint",
                         reason="A company can be GST-registered in a state other than its registered office. Informational only, never blocks."))

    # ---- cross-document consistency matrix (typed form, every document, the government record) ----
    sources = list(st.sources)
    if g is not None:
        sources.append(MSource("government", st.gst.source, {"gstin": v.clean(p.get("gstin")), "legal_name": g["legal_name"],
                                                             "address": f"{g.get('address', '')} {g.get('pincode', '')}".strip()}, authority=True))
    if len(sources) >= 2:
        st.matrix = build_matrix(sources, thr, [("x_" + d["key"], d["label"]) for d in custom_details(ctx.policy) if applies_to(d, st.country)],
                                 {d["key"]: ("x_" + d["key"] if any(t["key"] == d["key"] for t in custom_details(ctx.policy)) else "") for d in custom_docs(ctx.policy)})
        conf, mx = st.matrix["conflicts"], st.matrix
        r12_done = any(c.rule == "R12" and c.result in ("flag", "note") for c in st.checks.get("reconcile", []))
        if conf.get("legal_name") and not st.renames and not r12_done:
            why = "; ".join(sorted({c["reason"] for c in conf["legal_name"]}))
            st.add(Check("R12", FLAG, key="R12:docs", owner="procurement", kind="confirm", mode="document", source="Cross-document check",
                         expected="The same legal name on every document", found="Names differ between documents", title="review the legal-name difference between documents",
                         reason=why, detail="Compare the names in the consistency table below; ask the vendor for a name-change certificate if this was a rename."))
        if conf.get("account_holder"):
            why = "; ".join(sorted({c["reason"] for c in conf["account_holder"]}))
            st.add(Check("R16", FLAG, key="R16:holder", owner="finance", kind="confirm", mode="document", source="Cross-document check",
                         expected="Bank account holder = the vendor's legal name", found="Holder name differs", title="review the bank account holder name",
                         reason="The name on the bank document does not match the vendor's legal name. " + why))
        else:
            agreeing = [f"{r['cells']['account_holder']['value']} ({r['label']})" for r in mx["rows"]
                        if r["cells"]["account_holder"]["state"] == "ok" and r["cells"]["account_holder"]["value"]]
            if agreeing:
                st.add(Check("X2", PASS, name="Bank account name matches the legal name", mode="document", source="Cross-document check",
                             expected="The account holder is the vendor itself", found="; ".join(agreeing),
                             reason="The name on the bank account agrees with the vendor's legal name everywhere it appears."))
        if conf.get("address"):
            why = "; ".join(sorted({c["reason"] for c in conf["address"]}))
            st.add(Check("R25", FLAG, owner="procurement", kind="confirm", mode="document", source="Cross-document check",
                         expected="The address proof shows the address the GST registration shows", found="Addresses differ", title="review the address difference",
                         reason="The addresses on the documents do not match. " + why,
                         detail="Ask the vendor which address is current, for an address proof for the registered place of business, or for the amendment if they moved."))
        elif any(r["cells"]["address"]["state"] == "ok" for r in mx["rows"] if r["kind"] == "address_proof"):
            st.add(Check("R25", PASS, mode="document", source="Cross-document check", expected="Address proof matches the registered address", found="Matches",
                         reason="The address on the address proof matches the registered address (same PIN/ZIP and wording)."))
        missing = sum(1 for r in mx["rows"] for c in r["cells"].values() if c["state"] == "missing")
        bad = sum(len(x) for x in conf.values())
        st.add(Check("X1", PASS if not bad and not missing else INFO, name="Same details on every document", mode="document", source="Cross-document check",
                     expected="Every document shows the same value for each field",
                     found=f"{bad} difference{'s' if bad != 1 else ''}, {missing} missing · consistency score {mx['score']}/100",
                     reason="Advisory score: identifiers count double; a missing or unclear value counts against the score. The status is still decided by the rules, not the score."))

    # ---- R24: do ALL country signals (IDs, bank codes, document types, addresses, phone code) agree with the claimed country? ----
    claimed = st.country
    if claimed:
        cname = cn.name_of(claimed)
        sig: list[tuple[str, str]] = []
        r23_flagged = any(c.key == "R23" and c.blocking for cs in st.checks.values() for c in cs)     # the ID-format flag only, not R23v (manual verification)
        if not r23_flagged:
            for k in ("gstin", "pan", "cin"):
                if p.get(k):
                    sig.append(("IN", f"the {LABELS[k]} is an Indian ID"))
            found_ids = {m_.country for m_ in cn.detect(p.get("tax_id")) if m_.strong} if p.get("tax_id") else set()
            if len(found_ids) == 1:
                sig.append((next(iter(found_ids)), f"the tax ID is {cn.describe(next(m_ for m_ in cn.detect(p['tax_id']) if m_.strong))}"))
        if p.get("ifsc"):
            sig.append(("IN", "the bank code is an Indian IFSC"))
        iban_ = cn.flat(p.get("iban")) or cn.flat(p.get("bank_account"))
        if iban_[:2] in cn.IBAN_LEN and cn.iban_ok(iban_):
            sig.append((iban_[:2], f"the IBAN is {cn.name_of(iban_[:2])}'s"))
        sw_ = cn.flat(p.get("swift"))
        if len(sw_) >= 8 and sw_[4:6] in cn.COUNTRIES:
            sig.append((sw_[4:6], f"the SWIFT/BIC is {cn.name_of(sw_[4:6])}'s"))
        phone = (p.get("contact_phone") or "").strip()
        if phone.startswith("+"):
            from .extract import DIAL
            code = next((c_ for c_ in sorted(DIAL, key=len, reverse=True) if phone.startswith(c_)), "")
            if code and not (code == "+1" and claimed in ("US", "CA")):
                sig.append((DIAL[code], f"the contact phone starts with {code}"))
        indian_docs = {"gst_certificate": "GST certificate", "pan_card": "PAN card", "udyam_certificate": "Udyam certificate"}
        seen_doc = set()
        for f in st.doc_map:
            for pg in f["pages"]:
                if pg.get("foreign"):
                    continue
                for t in pg["types"]:
                    if t["doc_type"] in indian_docs and (f["name"], t["doc_type"]) not in seen_doc and not r23_flagged:
                        seen_doc.add((f["name"], t["doc_type"]))
                        sig.append(("IN", f"{f['name']} p.{pg['page']} is an Indian {indian_docs[t['doc_type']]}"))
            hints_by_page = (st.reads.get(f["sha"], {}).get("doc") or {}).get("hints", {})
            done_h = set()
            for pg_no, hs in hints_by_page.items():
                if len(hs) == 1 and hs[0] not in done_h and not next((pg for pg in f["pages"] if str(pg["page"]) == pg_no and pg.get("foreign")), None):
                    done_h.add(hs[0])
                    sig.append((hs[0], f"{f['name']} p.{pg_no} mentions {cn.name_of(hs[0])}"))
        clash = [d for c_, d in sig if c_ != claimed]
        if clash:
            st.add(Check("R24", FLAG, owner="vendor", kind="vendor", mode="computed", source="Cross-document check",
                         expected=f"Every signal points to {cname}", found=f"{len(clash)} of {len(sig)} signals point elsewhere",
                         title=f"confirm the country (they say {cname}, but the submission points elsewhere)",
                         reason=f"The vendor says it is based in {cname}, but: " + "; ".join(clash[:6]) + ("…" if len(clash) > 6 else "") + ".",
                         vendor_text=vtext("R24", claimed=cname, signals="; ".join(clash[:4])), vendor_fields=["country"], vendor_upload=True, meta={"signals": sig}))
        elif sig:
            st.add(Check("R24", PASS, mode="computed", source="Cross-document check", expected=f"Every signal points to {cname}", found=f"{len(sig)} signals, all {cname}",
                         reason=f"IDs, bank codes, documents, addresses and the phone code all agree with {cname}." + (" (Country inferred from them.)" if st.country_inferred else "")))

    # ---- R26: required documents, found by PAGE across one combined PDF or many files ----
    rows = ck.build({**p, "country": claimed}, st.doc_map, ctx.policy)
    st.checklist = [{"key": r.key, "label": r.label, "required": r.required, "why": r.why, "state": r.state, "where": r.where,
                     "link": list(r.link) if r.link else None} for r in rows]
    if rows:
        policy_mode = pol.get("require_documents", "if_uploaded")
        pack_types = {"vendor_registration_form", "pan_card", "gst_certificate", "cancelled_cheque_or_bank_letter", "bank_details_form", "address_proof",
                      "udyam_certificate", "tax_form_or_vat_certificate"} | {d["key"] for d in custom_docs(ctx.policy)}
        submitted_a_pack = any(t["doc_type"] in pack_types for f in st.doc_map for pg in f["pages"] for t in pg["types"])
        enforce = policy_mode == "always" or (policy_mode == "if_uploaded" and submitted_a_pack)
        miss_rows = ck.missing(rows)
        if enforce and st.matrix:
            req = [r for r in rows if r.required]
            apply_coverage(st.matrix, sum(1 for r in req if r.state == "found"), len(req), [r.label.split(" (")[0] for r in miss_rows])
        if miss_rows and enforce:
            lst = "; ".join(r.label for r in miss_rows)
            st.add(Check("R26", FLAG, owner="vendor", kind="vendor", mode="document", source="Document checklist", expected="All required documents present",
                         found="Missing: " + "; ".join(r.label.split(" (")[0] for r in miss_rows), title="send the missing documents",
                         reason="Required documents not found in the upload: " + lst + ".",
                         vendor_text=vtext("R26", list=lst), vendor_upload=True))
        elif miss_rows and not st.doc_map:
            # nothing was uploaded and documents are not enforced: say so plainly instead of calling every document "missing"
            for r in st.checklist:
                if r["required"] and r["state"] == "missing":
                    r["state"] = "not_provided"
            st.add(Check("R26", INFO, mode="document", source="Document checklist", expected="Supporting documents", found="No documents provided",
                         reason="No documents were provided. The details are typed only and could not be cross-checked against any document."))
        elif miss_rows:
            st.add(Check("R26", INFO, mode="document", source="Document checklist", found="Some documents not uploaded",
                         reason="Not every listed document was uploaded; the checklist is shown for information only."))
        else:
            st.add(Check("R26", PASS, mode="document", source="Document checklist", expected="All required documents present",
                         found=f"{sum(1 for r in rows if r.required)} of {sum(1 for r in rows if r.required)} found", reason="Every required document was found, whether in one PDF or several files."))

    # ---- your extra items: number and document status, for the case overview, the dashboard and the consistency table ----
    dets = {d["key"]: d for d in custom_details(ctx.policy) if applies_to(d, st.country)}
    docs_ = {r.key: r for r in rows}
    st.compliance = []
    thr_ = ctx.policy["name_match_threshold"]
    for d in custom_docs(ctx.policy):
        if d["key"] not in docs_ and d["key"] not in dets:
            continue                                                           # does not apply to this vendor
        row, det = docs_.get(d["key"]), dets.get(d["key"])
        st.compliance.append({"key": d["key"], "label": d["label"], "required": d.get("required", True), "doc": row.state if row else None, "where": row.where if row else "",
                              "number": None, "value": "", "doc_value": "",
                              "details": [{"label": extract.INFO_LABEL[f], "value": val} for f, val in st.item_details.get(d["key"], {}).items()]})
        doc_name = st.item_details.get(d["key"], {}).get("legal_name", "")
        case_name = (st.typed.get("legal_name") or "").strip() or next((s_.values["legal_name"] for s_ in st.sources if s_.kind not in (d["key"], "typed") and s_.values.get("legal_name")), "")
        doc_addr = st.item_details.get(d["key"], {}).get("address", "")
        others = [s_.values["address"] for s_ in st.sources if s_.kind != d["key"] and s_.values.get("address")]
        st.compliance[-1]["address_check"] = "" if not doc_addr else ("none" if not others else ("ok" if any(same_address(doc_addr, o) for o in others) else "differs"))
        st.compliance[-1]["name_check"] = ("" if not (doc_name and case_name) else ("ok" if v.names_match(doc_name, case_name, thr_) else "differs"))
    for key, det in dets.items():
        item = next((c for c in st.compliance if c["key"] == key), None)
        if item is None:
            item = {"key": key, "label": det.get("item") or det["label"], "required": det["required"], "doc": None, "where": "", "number": None, "value": "", "doc_value": ""}
            st.compliance.append(item)
        val, src = _item_value(st, key)
        item["value"], item["number_src"] = val, src
        item["number_label"] = det["label"]
        item["number"] = ("ok" if format_ok(det["format"], val) else "bad") if val else ("missing" if det["required"] else "optional")
        item["doc_value"] = next((s_.values["x_" + key] for s_ in st.sources if s_.kind == key and s_.values.get("x_" + key)), "")
    if st.matrix and st.compliance:                                           # a required document that was not provided is a visible row in the consistency table
        fields = st.matrix["fields"]
        for c in st.compliance:
            xk = "x_" + c["key"]
            if c["number"] is not None and xk not in dict(fields):
                fields.append((xk, c.get("number_label") or c["label"]))
                for r_ in st.matrix["rows"]:
                    r_["cells"][xk] = {"state": "na", "value": "", "reason": ""}
        for c in st.compliance:
            if c["doc"] == "missing":
                cells = {f: {"state": "na", "value": "", "reason": ""} for f in st.matrix["rows"][0]["cells"]}      # every column, like every other row
                if "x_" + c["key"] in cells:
                    cells["x_" + c["key"]] = {"state": "missing", "value": "", "reason": f"The {c['label']} was not provided."}
                st.matrix["rows"].append({"label": c["label"], "ref": "Not provided", "kind": c["key"], "cells": cells, "absent": True})
    # evidence table
    def doc(k): return st.doc_values.get(k, "")
    hcells = [r["cells"].get("account_holder", {}).get("state") for r in (st.matrix or {}).get("rows", [])]
    holder_res = "mismatch" if "bad" in hcells else ("match" if "ok" in hcells else "")
    gp = (st.gst.fields if g else {}) or {}
    pan_ok = "match" if (st.derived_pan or (pan_used and g and v.pan_from_gstin(v.clean(p.get('gstin'))) == pan_used)) else ("mismatch" if flagged(st, "R08") else "")
    st.table = [
        {"label": "Legal name", "declared": declared, "document": doc("legal_name"), "government": gp.get("legal_name", ""), "result": result_of.get("legal_name", "")},
        {"label": "Trade name", "declared": p.get("trade_name", ""), "document": doc("trade_name"), "government": gp.get("trade_name", ""), "result": result_of.get("trade_name", "")},
        {"label": "PAN", "declared": p.get("pan", ""), "document": doc("pan"), "government": v.pan_from_gstin(v.clean(p.get("gstin"))) if g else "", "result": pan_ok},
        {"label": "GSTIN", "declared": p.get("gstin", ""), "document": doc("gstin"), "government": gp.get("gstin", ""), "result": "verified" if g else ("blocked" if "gstin" in st.blocked else "")},
        {"label": "State", "declared": v.state_of_gstin(p.get("gstin", "")) if p.get("gstin") and "gstin" not in st.blocked else "", "document": "", "government": gp.get("state", ""), "result": "match" if g else ""},
        {"label": "CIN", "declared": p.get("cin", ""), "document": doc("cin"), "government": "", "result": "format ok" if cin and "cin" not in st.blocked else ""},
        {"label": "Account holder", "declared": p.get("account_holder", ""), "document": doc("account_holder"), "government": "", "result": holder_res},
        {"label": "IFSC", "declared": p.get("ifsc", ""), "document": doc("ifsc"), "government": next((e["value"] for e in st.evidence if e["field"] == "ifsc.bank"), ""), "result": "exists" if "bank" not in st.blocked and p.get("ifsc") else ""},
    ]
    if st.country != "IN":
        acct_f = cn.flat(p.get("iban")) or p.get("bank_account", "")
        st.table = [
            {"label": "Legal name", "declared": declared, "document": doc("legal_name"), "government": "", "result": result_of.get("legal_name", "")},
            {"label": "Tax ID", "declared": p.get("tax_id", ""), "document": doc("tax_id"), "government": "", "result": "format ok" if "tax_id" not in st.blocked and p.get("tax_id") else ("blocked" if p.get("tax_id") else "")},
            {"label": "Bank account / IBAN", "declared": acct_f, "document": doc("iban") or doc("bank_account"), "government": "", "result": "format ok" if "bank" not in st.blocked and acct_f else ""},
            {"label": "SWIFT / routing", "declared": p.get("swift") or p.get("routing_code", ""), "document": doc("swift") or doc("routing_code"), "government": "", "result": ""},
            {"label": "Account holder", "declared": p.get("account_holder", ""), "document": doc("account_holder"), "government": "", "result": holder_res},
        ]
    hidden = {lbl for lbl, k in {"PAN": "pan", "GSTIN": "gstin", "State": "gstin", "CIN": "cin", "Account holder": "bank", "IFSC": "bank",
                                 "Bank account / IFSC": "bank", "SWIFT / routing": "bank"}.items() if not detail_on(ctx.policy, k)}
    st.table = [r for r in st.table if r["label"] not in hidden]            # a detail switched off in Settings has no row
    for d in custom_details(ctx.policy):
        val = (st.typed.get("x_" + d["key"]) or "").strip()
        if val and applies_to(d, st.country):
            seen_doc = next((s_.values["x_" + d["key"]] for s_ in st.sources if s_.kind == d["key"] and s_.values.get("x_" + d["key"])), "")
            ok_fmt = format_ok(d["format"], val)
            st.table.append({"label": d["label"], "declared": val, "document": seen_doc, "government": "",
                             "result": ("match" if v.clean(val) == v.clean(seen_doc) else "mismatch") if (seen_doc and ok_fmt) else ("format ok" if ok_fmt else "needs review")})
    r12 = next((c for c in st.checks["reconcile"] if c.rule == "R12"), None)
    return {"match": "Names agree", "explained": "Name difference explained by evidence", "mismatch": "Name difference needs review", "needs review": "Rename needs confirmation"}.get(
        result_of.get("legal_name", ""), (r12.reason if r12 and r12.result == SKIP else "Nothing to reconcile yet"))
