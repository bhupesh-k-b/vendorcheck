"""The rule catalogue (R01-R22), check results, and the vendor-message templates.

One module so a non-engineer can read what the system checks and what it tells vendors.
Thresholds and accepted evidence live in policy.yaml, not here."""
from dataclasses import dataclass, field, asdict
from typing import Any

# result values of a check
PASS, NOTE, FLAG, WAIT, REJECT, SKIP, INFO = "pass", "note", "flag", "wait", "reject", "skip", "info"
BLOCKING = {FLAG, WAIT}

OWNERS = ("vendor", "procurement", "finance", "system")

# id -> (plain-language name, source, default owner when it fails)
RULES: dict[str, tuple[str, str, str]] = {
    "R01": ("Already in the vendor master?", "Vendor master", "procurement"),
    "R02": ("Bank account used by a different PAN?", "Vendor master", "finance"),
    "R03": ("Required details present", "Submission", "vendor"),
    "R04": ("Document is what it claims to be and is legible", "Document reader", "vendor"),
    "R05": ("Key numbers read with confidence", "Document reader (double read)", "vendor"),
    "R06": ("GSTIN format, check digit and type", "Offline check", "vendor"),
    "R07": ("PAN format and holder type", "Offline check", "vendor"),
    "R08": ("PAN inside the GSTIN equals the PAN given", "Offline check", "vendor"),
    "R09": ("Bank account number and IFSC", "RBI IFSC dataset", "vendor"),
    "R10": ("CIN format and company class", "Offline check", "vendor"),
    "R11": ("GST registration is active", "GST network", "vendor"),
    "R12": ("Legal name agrees across sources", "Reconcile", "procurement"),
    "R13": ("GST returns filed without gaps", "GST network", "procurement"),
    "R14": ("PAN is valid and operative", "GST (derived) / assisted", "vendor"),
    "R15": ("Company is active at MCA", "MCA", "system"),
    "R16": ("Bank account is active and in the vendor's name", "Penny drop / finance", "finance"),
    "R17": ("Udyam (MSME) registration valid", "Udyam", "vendor"),
    "R18": ("Bank details changed on an approved vendor", "Vendor master", "finance"),
    "R19": ("PAN or account on the blocklist", "policy.yaml", "system"),
    "R20": ("Source reachable", "Adapter", "system"),
    "R21": ("GST taxpayer type and e-invoicing", "GST network", "procurement"),
    "R22": ("Second person approves every manual resolution", "Workflow", "finance"),
    "R23": ("Tax ID belongs to the country the vendor claims", "Offline check", "vendor"),
    "R24": ("Every country signal agrees with the claimed country", "Cross-document check", "vendor"),
    "R25": ("Address proof matches the registered address", "Cross-document check", "procurement"),
    "R26": ("Required documents are present", "Document checklist", "vendor"),
    "R27": ("Vendor categorised (goods/services, expense category, department owner)", "Procurement", "procurement"),
    "R28": ("Configured payment terms equal the negotiated terms", "Procurement", "procurement"),
}

# plain-language wording for what each owner is asked to do, used in the banner sentence
OWNER_LABEL = {"vendor": "the vendor", "procurement": "procurement", "finance": "finance", "system": "the system"}


@dataclass
class Check:
    rule: str
    result: str
    key: str = ""                 # resolution key; defaults to the rule id
    name: str = ""
    owner: str = ""
    expected: str = ""
    found: str = ""
    source: str = ""
    mode: str = ""
    reason: str = ""
    requirement: str = ""         # which approval requirement this evidence supports (policy.yaml)
    title: str = ""               # short imperative: "confirm the bank account" (for banner + tasks)
    detail: str = ""              # longer instruction for the reviewer
    kind: str = "confirm"         # confirm | evidence | vendor | retry
    assist: str = ""              # gst | udyam | mca | pan  -> offers the assisted-check panel
    vendor_text: str = ""         # sentence in the vendor message (already masked)
    vendor_fields: list[str] = field(default_factory=list)   # inputs the vendor portal should show
    vendor_upload: bool = False
    condition: str = ""           # approval condition text (open advisory)
    recheck_days: int = 0
    reapply: bool = False         # a rejection that the vendor can answer with a new GSTIN
    evidence_ref: str = ""
    stage: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        name, source, owner = RULES.get(self.rule, (self.rule, "", ""))
        self.key = self.key or self.rule
        self.name = self.name or name
        self.source = self.source or source
        if self.result in BLOCKING and not self.owner:
            self.owner = owner

    @property
    def blocking(self) -> bool:
        return self.result in BLOCKING

    def to_dict(self) -> dict:
        d = asdict(self)
        d["blocking"] = self.blocking
        return d


# ---------- vendor message templates (no free-form AI text) ----------
# placeholders are filled with already-masked values. Never mention internal signals or other vendors.
VENDOR_TEMPLATES = {
    "R23_wrong_country": "The tax ID you gave ({id}) looks like {found}, but you told us you are based in {claimed}. Please send your {claimed} tax ID ({example}), or correct the country if you are based elsewhere.",
    "R23_invalid": "The tax ID you gave ({id}) has a typing error: it has the shape of a {claimed} {type} but fails its check digit. Please check it.",
    "R23_unrecognised": "We do not recognise the tax ID you gave ({id}) as a {claimed} tax ID. Expected: {example}.",
    "R23_personal": "Please do not send personal IDs such as an SSN. Send your business's tax ID ({example}).",
    "R09_foreign": "Your bank details need a correction: {issues}",
    "R24": "You told us you are based in {claimed}, but your submission points to other countries: {signals}. Please confirm the country you are based in, and send documents and IDs that match it.",
    "R26": "We still need these documents: {list}. You can send them as separate files or all together in one PDF.",
    "R23_notfound": "The tax ID you gave ({id}) could not be confirmed on the official register for {claimed}. Please check it, or send the correct one.",
    "R03": "We still need: {missing}.",
    "R04": "We could not use the file '{file}': {why}. Please upload the correct, clearly readable document.",
    "R04_foreign": "Pages {pages} of '{file}' show bank details for another account holder ({holder}), not {vendor}. Please upload a cancelled cheque or bank letter for your own business account.",
    "R05": "We could not read the {label} clearly on your document (we saw something ending {seen}). Please type it exactly as printed.",
    "R05_conflict": "The {label} is not the same on all your documents ({where}). Please confirm the correct one.",
    "R06_format": "The GSTIN you gave ({gstin}) is not in a valid format. Please check it against your GST certificate.",
    "R06_check_digit": "The GSTIN you gave ({gstin}) has a typing error: its last character does not match. Please check it against your GST certificate.",
    "R06_tax_collector": "The GSTIN you gave ({gstin}) is a tax-collector registration (the 14th character is C). It cannot be used on supply invoices. Please send your regular GSTIN for the state you supply from.",
    "R06_tax_deductor": "The GSTIN you gave ({gstin}) is a tax-deductor registration (the 14th character is D). It cannot be used on supply invoices. Please send your regular GSTIN for the state you supply from.",
    "R06_other": "The GSTIN you gave ({gstin}) is not a regular registration. Please send your regular GSTIN.",
    "R07": "The PAN you gave ({pan}) does not look right for your business type. Please check it against your PAN card.",
    "R08": "The PAN inside the GSTIN you gave (…{gstin_pan}) is different from the PAN you gave (…{pan}). One of them has a mistake. Please check both against your GST certificate and PAN card and send the correct values.",
    "R09_account": "The bank account number you gave ({account}) is not valid or does not match its confirmation. Please re-enter it.",
    "R09_ifsc": "The IFSC you gave ({ifsc}) was not found in the bank list. Please check it on your cheque leaf or bank statement.",
    "R10": "The CIN you gave ({cin}) is not valid for your company name. Please check it against your certificate of incorporation.",
    "R11_missing": "We could not find the GSTIN you gave ({gstin}) in the GST records. Please check it, or send your correct GSTIN.",
    "R11_suspended": "Your GST registration ({gstin}) shows as suspended. Please contact your GST officer, or send another active GSTIN.",
    "R11_cancelled": "Your GST registration ({gstin}) is cancelled, so we cannot onboard you with it. If you hold another active GSTIN, please apply again with that one.",
    "R16_invalid": "We could not verify the bank account ({account}). Please check the account number and IFSC and send them again.",
    "R17": "The Udyam number you gave ({udyam}) could not be confirmed. Please check it against your Udyam certificate.",
    "R14_inoperative": "Your PAN is marked inoperative (not linked to Aadhaar). Please link it and tell us once done.",
}


def vtext(code: str, **kw: str) -> str:
    return VENDOR_TEMPLATES[code].format(**kw)


def label_of(rule_field: str) -> str:
    return {"gstin": "GSTIN", "pan": "PAN", "cin": "CIN", "bank_account": "bank account number", "ifsc": "IFSC"}.get(rule_field, rule_field)
