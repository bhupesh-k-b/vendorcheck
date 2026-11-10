"""Simulated registry, for test cases on FICTIONAL vendors.

A fictional company can never exist in the real GST registry, so it can never be approved by a live answer. A simulated submission therefore
runs with a recorded (synthetic) registry response and the simulation policy, and is labelled Simulated everywhere. Documents are still read
for real by the same reader. A simulated approval never writes to the vendor master. Real submissions never take this path."""
from copy import deepcopy
from dataclasses import replace

from .adapters.gst import RecordedGst
from .context import Ctx
from .policy import simulation_policy
from .validators import with_gstin_check_char

# the fictional vendor used by the happy-path test case (Kaveri Precision Components, Pune)
KAVERI_NAME = "KAVERI PRECISION COMPONENTS PRIVATE LIMITED"
KAVERI_GSTIN = with_gstin_check_char("27AAACK5521D1Z")


def kaveri_response() -> dict:
    gstin = KAVERI_GSTIN
    return {"success": True, "_synthetic": True, "gstin": gstin, "data": {
        "gstin": gstin, "legal_name": KAVERI_NAME, "trade_name": "KAVERI PRECISION COMPONENTS", "status": "Active", "taxpayer_type": "Regular",
        "business_constitution": "Private Limited Company", "registration_date": "2018-01-01", "cancellation_date": None, "state_code": gstin[:2],
        "address": "Plot 41, MIDC Bhosari, Pune, Maharashtra", "pincode": "411026", "einvoice_status": "Yes", "block_status": "Unblocked"}}


def sim_ctx(base: Ctx, fixtures: dict | None = None) -> Ctx:
    """The base context with the registry replaced by recorded responses, the simulation policy, and sim=True (cases are flagged and kept out of the vendor master)."""
    gst = RecordedGst(fixtures if fixtures is not None else {KAVERI_GSTIN: kaveri_response()})
    return replace(base, sim=True, enrich=False, gst=gst, policy=simulation_policy(deepcopy(base.policy)))
