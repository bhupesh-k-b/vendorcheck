"""Cross-document consistency matrix. Pure functions: no I/O, no model.

Rows are the places a value can come from (the typed form, each uploaded document, the government record);
columns are the fields. Each cell is:
    ok       this source agrees with the consensus value
    alone    this is the only source that shows the field: nothing to compare it with (never counted as agreement)
    bad      this source disagrees (the reason names both values)
    missing  this kind of document normally carries the field but it is not there   (shown as O)
    unclear  the value could not be read with confidence (never counted as agreeing)
    na       this kind of document does not carry the field (blank)
The consensus is the value most sources agree on; the government record breaks ties. If nothing wins,
every differing source is marked bad. The score is advisory: the status is still decided by the rules."""
import re
from dataclasses import dataclass, field

from . import validators as v

FIELDS = [("legal_name", "Legal name"), ("tax_id", "Tax ID"), ("pan", "PAN"), ("gstin", "GSTIN"), ("cin", "CIN"),
          ("bank_account", "Bank account no."), ("ifsc", "IFSC"), ("account_holder", "Account holder"), ("address", "Address")]
WEIGHT = {"address": 1, "tax_id": 2, "pan": 2, "gstin": 2, "cin": 2, "bank_account": 2, "ifsc": 2, "legal_name": 1, "account_holder": 1}
EXPECTED = {
    "typed": ["legal_name", "tax_id", "pan", "gstin", "cin", "bank_account", "ifsc", "account_holder", "address"],
    "vendor_registration_form": ["legal_name", "tax_id", "pan", "gstin", "cin", "bank_account", "ifsc"],
    "tax_form_or_vat_certificate": ["tax_id", "legal_name"],
    "pan_card": ["pan", "legal_name"],
    "gst_certificate": ["gstin", "pan", "legal_name", "address"],
    "address_proof": ["address"],
    "incorporation_or_name_change_certificate": ["cin", "legal_name"],
    "stock_exchange_filing": ["cin", "legal_name"],
    "cancelled_cheque_or_bank_letter": ["bank_account", "ifsc", "account_holder"],
    "bank_details_form": ["bank_account", "ifsc", "account_holder"],
    "udyam_certificate": ["legal_name"],
    "government": ["gstin", "pan", "legal_name", "address"],
}
DOC_LABEL = {"typed": "Form typed on the platform", "vendor_registration_form": "Registration form", "pan_card": "PAN card",
             "gst_certificate": "GST certificate", "incorporation_or_name_change_certificate": "Incorporation / name-change certificate",
             "stock_exchange_filing": "Stock-exchange filing", "cancelled_cheque_or_bank_letter": "Cancelled cheque / bank letter",
             "bank_details_form": "Bank details form (NEFT/RTGS)", "tax_form_or_vat_certificate": "Tax form / VAT certificate", "tax_filing_document": "Tax filing document",
             "address_proof": "Address proof", "other_certificate": "Other certificate",
             "udyam_certificate": "Udyam certificate", "government": "Government record (GST, live)"}


@dataclass
class Source:
    kind: str                                   # key of EXPECTED
    ref: str = ""                               # file name + pages
    values: dict = field(default_factory=dict)  # field -> value
    unclear: set = field(default_factory=set)  # fields read with low confidence
    authority: bool = False                     # government record: breaks ties
    foreign: str = ""                           # a bank document in somebody else's name: shown, never used as the vendor's
    title: str = ""                             # the name of a document you added in Settings
    proprietor: str = ""                        # a proprietor's PAN card carries the person's name, not the firm's: expected

    @property
    def label(self) -> str:
        return self.title or DOC_LABEL.get(self.kind, self.kind)


def norm(fld: str, value: str) -> str:
    if fld in ("legal_name", "account_holder"):
        return v.normalise_name(value)
    if fld == "bank_account":
        v_ = re.sub(r"[\s\-]", "", value or "").upper()
        return v_ if re.match(r"[A-Z]{2}\d{2}", v_) else re.sub(r"\D", "", value or "")       # an IBAN keeps its letters
    return v.clean(value)


def _pins(text: str) -> set[str]:
    return set(re.findall(r"(?<!\d)\d{5,6}(?!\d)", text or ""))


def same_address(a: str, b: str) -> bool:
    """The same address written two ways: equal PIN/ZIP and real word overlap, or (without PINs) a high text match."""
    from rapidfuzz import fuzz
    na, nb = re.sub(r"[^A-Z0-9 ]", " ", a.upper()), re.sub(r"[^A-Z0-9 ]", " ", b.upper())
    ratio = fuzz.token_set_ratio(na, nb)
    pa, pb = _pins(a), _pins(b)
    if pa and pb:
        return bool(pa & pb) and ratio >= 45
    return ratio >= 70


def _same(fld: str, a: str, b: str, threshold: float) -> bool:
    if fld == "address":
        return same_address(a, b)
    if fld in ("legal_name", "account_holder"):
        if v.names_match(a, b, threshold):
            return True
        return fld == "account_holder" and unit_of(a, b)
    return norm(fld, a) == norm(fld, b)


def unit_of(a: str, b: str) -> bool:
    """A company's own unit account: 'MUNITIONS INDIA LIMITED O F KHAMARIA' belongs to 'MUNITIONS INDIA LIMITED'.
    True when one name is the other plus extra words (a unit, branch or division) and the shorter one has at least three words."""
    ca, cb = v.normalise_name(a).replace(" ", ""), v.normalise_name(b).replace(" ", "")       # the text reader often drops spaces
    short, long_ = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    return len(short) >= 12 and len(long_) > len(short) and long_.startswith(short)


def _show(fld: str, value: str) -> str:
    return value


def with_derived_pan(sources: list[Source]) -> None:
    """A GSTIN contains the PAN; where a source shows a GSTIN but no PAN, use the PAN inside it."""
    for s in sources:
        g = v.clean(s.values.get("gstin"))
        if len(g) == 15 and not s.values.get("pan") and s.kind in ("gst_certificate", "government"):
            s.values["pan"] = v.pan_from_gstin(g)


def build(sources: list[Source], threshold: float = 92, extra: list[tuple[str, str]] | None = None, doc_fields: dict[str, str] | None = None) -> dict:
    """`extra`: (field, label) for the numbers you added in Settings; `doc_fields`: the document you added -> the number it carries."""
    extra = extra or []
    ALL = FIELDS + [(f, l) for f, l in extra if f not in dict(FIELDS)]
    fnames = dict(ALL)
    expected = {**EXPECTED, "typed": EXPECTED["typed"] + [f for f, _ in extra], **{k: ["legal_name", "address"] + ([f] if f else []) for k, f in (doc_fields or {}).items()}}
    custom_kinds = set(doc_fields or {})
    optional_typed = {"account_holder", "address"} | {f for f, _ in extra}
    with_derived_pan(sources)
    present = {f for s in sources for f in s.values}
    applicable = [f for f, _ in ALL if f in present or f == "legal_name"]
    consensus: dict[str, str | None] = {}
    for f in applicable:
        ref_field = "legal_name" if f == "account_holder" else f
        votes: list[tuple[str, int]] = []       # (representative value, weight)
        for s in sources:
            if s.foreign:
                continue
            val = s.values.get(ref_field) if f != "account_holder" else s.values.get("legal_name")
            if not val or ref_field in s.unclear or (f == "account_holder" and "legal_name" in s.unclear):
                continue
            if f == "account_holder" and s.kind in ("vendor_registration_form", "cancelled_cheque_or_bank_letter"):
                continue            # holder names are checked against the legal name, not used to define it
            w = 2 if s.authority else 1
            for i, (rep, n) in enumerate(votes):
                if _same(ref_field, rep, val, threshold):
                    votes[i] = (rep, n + w)
                    break
            else:
                votes.append((val, w))
        votes.sort(key=lambda t: -t[1])
        consensus[f] = votes[0][0] if votes and (len(votes) == 1 or votes[0][1] > votes[1][1]) else None

    rows, conflicts = [], {}
    for s in sources:
        cells = {}
        for f, _ in ALL:
            if s.foreign and f in ("bank_account", "ifsc", "account_holder", "legal_name"):
                cells[f] = {"state": "foreign", "value": s.values.get(f, ""), "reason": f"{s.label} is in the name of {s.foreign}, not the vendor."}
                continue
            if s.proprietor and f == "legal_name":
                cells[f] = {"state": "proprietor", "value": s.proprietor,
                            "reason": f"The PAN card is in the proprietor's own name ({s.proprietor}). That is expected for a proprietorship, so it is not compared with the firm's name."}
                continue
            if f not in applicable or f not in expected.get(s.kind, []) or (s.kind == "typed" and f in optional_typed and not s.values.get(f)) \
                    or (s.kind in custom_kinds and f in ("legal_name", "address") and not s.values.get(f)):      # a document you added need not state a name or address
                cells[f] = {"state": "na", "value": "", "reason": ""}      # the typed holder name is optional: blank is neutral, not a gap
                continue
            val = s.values.get(f, "")
            if f in s.unclear:
                cells[f] = {"state": "unclear", "value": val, "reason": f"{s.label}: the {fnames[f].lower()} could not be read clearly."}
            elif not val:
                cells[f] = {"state": "missing", "value": "", "reason": f"{s.label} does not show the {fnames[f].lower()}."}
            elif f != "account_holder" and sum(1 for o in sources if not o.foreign and o.values.get(f) and f not in o.unclear) < 2:
                cells[f] = {"state": "alone", "value": val, "reason": f"Only {s.label} shows the {fnames[f].lower()}, so there is nothing to compare it with."}
            else:
                ref = consensus.get(f)
                if f == "account_holder":
                    ref = consensus.get("legal_name")
                ok = ref is not None and _same(f, val, ref, threshold)
                if ok:
                    cells[f] = {"state": "ok", "value": val, "reason": ""}
                else:
                    others = "; ".join(f"{o.label} shows {_show(f, o.values.get(f, ''))}" for o in sources
                                       if o is not s and not o.foreign and o.values.get(f) and not _same(f, o.values[f], val, threshold)
                                       and f not in o.unclear)
                    why = (f"{s.label} shows {_show(f, val)}" + (f", but {others}" if others else
                           (f", which differs from the consensus {_show(f, ref)}" if ref else "")))
                    cells[f] = {"state": "bad", "value": val, "reason": why}
                    conflicts.setdefault(f, []).append({"source": s.label, "ref": s.ref, "value": val, "reason": why})
        rows.append({"label": s.label, "ref": s.ref, "kind": s.kind, "cells": cells})

    got = total = 0
    for r in rows:
        for f, c in r["cells"].items():
            if c["state"] in ("ok", "bad", "missing", "unclear"):
                total += WEIGHT.get(f, 2)
                got += WEIGHT.get(f, 2) if c["state"] == "ok" else 0
    score = round(100 * got / total) if total else None
    return {"fields": [(f, l) for f, l in ALL if f in applicable], "rows": rows, "conflicts": conflicts, "score": score, "band": band_of(score),
            "consensus": {f: c for f, c in consensus.items()}, "cells_checked": total, "agreement": score, "coverage": None}


def band_of(score) -> str:
    return "strong" if (score or 0) >= 90 else "review" if (score or 0) >= 70 else "weak"


def apply_coverage(matrix: dict, found: int, required: int, missing: list[str]) -> None:
    """Fold the required-documents checklist into the score: details can agree perfectly across the documents that WERE sent
    and still be a poor submission if required documents are missing or belong to somebody else. Advisory, like the rest of the score."""
    if not matrix or not required or matrix.get("score") is None:
        return
    factor = found / required
    matrix["coverage"] = {"found": found, "required": required, "missing": missing}
    matrix["score"] = round(matrix["agreement"] * factor)
    matrix["band"] = band_of(matrix["score"])
