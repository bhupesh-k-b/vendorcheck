"""Test harness. Vendors here are FICTIONAL and their GST 'responses' are labelled synthetic: they exercise
the engine only. Real government responses are captured separately (scripts/capture_fixtures.py) once a key exists."""
import pytest

from vendorcheck import db
from vendorcheck import validators as v
from vendorcheck.adapters import ifsc
from vendorcheck.adapters.gst import RecordedGst
from vendorcheck.context import Ctx
from vendorcheck.policy import load_policy, simulation_policy
from vendorcheck.reader import StaticReader

# fictional vendor
PAN = "AAACB1234C"
GSTIN = v.with_gstin_check_char("27AAACB1234C1Z")
NAME = "BLUE HERON TRADING PRIVATE LIMITED"
CIN = "U51909MH2015PTC123456"
BANK = ("50100123456789", "HDFC0000001")


def gst_fixture(gstin=GSTIN, legal=NAME, trade="BLUE HERON TRADING", status="Active", ttype="Regular", einv="Yes", cancel=None):
    return {"success": True, "_synthetic": True, "gstin": gstin, "credits_remaining": 0,
            "data": {"gstin": gstin, "legal_name": legal, "trade_name": trade, "status": status, "taxpayer_type": ttype, "business_constitution": "Private Limited Company",
                     "registration_date": "2018-01-01", "cancellation_date": cancel, "state_code": gstin[:2], "address": "1 Test Road", "pincode": "400001",
                     "einvoice_status": einv, "block_status": "Unblocked"}}


class CountingGst(RecordedGst):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.calls = []

    def lookup(self, gstin):
        self.calls.append(gstin)
        return super().lookup(gstin)


COMMERCIAL = dict(vendor_type="goods", expense_category="Raw materials", department_owner="Procurement", negotiated_terms="Net 45", system_terms="45")


def form(**over):
    d = dict(legal_name=NAME, gstin=GSTIN, pan=PAN, cin=CIN, bank_account=BANK[0], bank_account_confirm=BANK[0], ifsc=BANK[1],
             contact_name="Asha Rao", contact_email="asha@blueheron.example", contact_phone="9000000001", **COMMERCIAL)
    d.update(over)
    return d


def make_ctx(fixtures=None, reader=None, sim=True, policy=None, url="sqlite://") -> Ctx:
    if not ifsc.dataset_ready():
        ifsc.download()
    pol = policy or load_policy()
    pol = {**pol, "require_documents": pol.get("require_documents_override", "off")}      # tests about other rules run with the checklist off
    return Ctx(engine=db.make_engine(url), policy=simulation_policy(pol) if sim else pol,
               gst=CountingGst(fixtures if fixtures is not None else {GSTIN: gst_fixture()}), reader=reader or StaticReader({}), sim=False, enrich=False)


@pytest.fixture
def ctx():
    return make_ctx()
