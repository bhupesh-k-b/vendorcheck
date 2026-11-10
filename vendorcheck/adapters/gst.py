"""GST adapter: live data via gstinapi.in (relays GST network data).

Docs: https://www.gstinapi.in/docs   Auth: header `x-api-key`.   GET /v1/gstin/{gstin}?include=profile
Errors: 400 bad format (no charge), 401 bad key, 402 out of credits, 404 not registered, 429 over 60/min,
502 upstream down (safe to retry). Retry only 429/502, at most 3 attempts.

Never fabricates: no key => `not_configured`; Settings outage switch => `simulated_outage` (labelled).
The sandbox GSTIN returns a fixed sample and is mode `sandbox`, which never satisfies approval."""
import json
import time
from pathlib import Path

import httpx

from .. import config, db
from ..validators import SANDBOX_GSTIN, STATES
from .base import AdapterResult, now_iso

BASE = "https://www.gstinapi.in"
SOURCE = "gstinapi.in"
SIMULATE_KEY = "simulate_gst_outage"
CREDITS_KEY = "gst_credits_remaining"

_ERRORS = {400: ("bad_format", "GSTIN format rejected by the provider."),
           401: ("auth", "The GST API key is missing or invalid."),
           402: ("credits", "The GST API account is out of credits."),
           403: ("auth", "The GST API account is deactivated."),
           404: ("not_found", "This GSTIN is not registered in the GST database."),
           429: ("rate_limited", "GST API rate limit reached."),
           502: ("upstream", "The GST network is temporarily unavailable."),
           503: ("upstream", "The PAN source is temporarily unavailable.")}


def parse_lookup(raw: dict) -> dict:
    """Map a gstinapi.in /v1/gstin response to our field names."""
    d = raw.get("data") or {}
    code = d.get("state_code") or (d.get("gstin") or "")[:2]
    return {
        "gstin": d.get("gstin", ""), "legal_name": d.get("legal_name") or "", "trade_name": d.get("trade_name") or "",
        "status": d.get("status") or "", "taxpayer_type": d.get("taxpayer_type") or "",
        "constitution": d.get("business_constitution") or "", "registration_date": d.get("registration_date") or "",
        "cancellation_date": d.get("cancellation_date") or "", "state_code": code, "state": STATES.get(code, ""),
        "address": d.get("address") or "", "pincode": d.get("pincode") or "",
        "einvoice_status": d.get("einvoice_status") or "", "block_status": d.get("block_status") or "",
    }


def parse_pan(raw: dict) -> dict:
    nm = raw.get("name_match") or {}
    return {"pan": raw.get("pan", ""), "name": raw.get("name") or "", "status": raw.get("status") or "", "verified": bool(raw.get("verified")),
            "level": raw.get("level", "basic"), "name_match_score": nm.get("score"), "name_matched": nm.get("matched"),
            "credits_charged": raw.get("credits_charged")}


def parse_returns(raw: dict) -> dict:
    rets = raw.get("returns") or []
    return {"fy": raw.get("fy", ""), "returns": rets,
            "gstr3b_periods": sorted({r["return_period"] for r in rets if r.get("return_type") == "GSTR-3B" and r.get("filing_status") == "Filed"})}


class GstApi:
    """Live adapter. `engine` gives access to the 24h cache and the outage switch."""

    def __init__(self, engine, api_key: str | None = None, client: httpx.Client | None = None, sleep=time.sleep):
        self.engine = engine
        self.api_key = config.gstin_key() if api_key is None else api_key
        self.client = client or httpx.Client(timeout=20)
        self.sleep = sleep

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str, params: dict | None = None) -> tuple[int, dict]:
        last: tuple[int, dict] = (0, {})
        for attempt in range(3):
            try:
                r = self.client.get(BASE + path, params=params, headers={"x-api-key": self.api_key})
            except httpx.TimeoutException:
                last = (-1, {"error": "timeout"})
            except httpx.HTTPError as e:
                last = (-2, {"error": str(e)})
            else:
                try:
                    body = r.json()
                except ValueError:
                    body = {"error": r.text[:200]}
                if r.status_code not in (429, 502):
                    return r.status_code, body
                last = (r.status_code, body)
            if attempt < 2:
                self.sleep(2 ** attempt)
        return last

    def _result(self, status: int, body: dict, parse, ref: str, mode: str) -> AdapterResult:
        if status == 200 and body.get("success"):
            if "credits_remaining" in body:
                db.set_kv(self.engine, CREDITS_KEY, str(body["credits_remaining"]))
            return AdapterResult(True, parse(body), SOURCE, mode, raw=body, ref=ref)
        if status == -1:
            return AdapterResult(False, source=SOURCE, mode=mode, error="timeout", message="The GST API timed out.")
        if status == -2:
            return AdapterResult(False, source=SOURCE, mode=mode, error="network", message="Could not reach the GST API.")
        kind, msg = _ERRORS.get(status, ("upstream", f"Unexpected GST API response ({status})."))
        return AdapterResult(False, source=SOURCE, mode=mode, raw=body, error=kind, message=body.get("error") or msg, ref=ref)

    def _guard(self) -> AdapterResult | None:
        if db.get_kv(self.engine, SIMULATE_KEY) == "1":
            return AdapterResult(False, source=SOURCE, mode="live", error="simulated_outage",
                                 message="SIMULATED outage: the Settings switch is making the GST source fail on purpose.")
        if not self.configured:
            return AdapterResult(False, source=SOURCE, mode="live", error="not_configured",
                                 message="GSTINAPI_KEY is not set, so GST cannot be checked live.")
        return None

    def lookup(self, gstin: str) -> AdapterResult:
        if (blocked := self._guard()):
            return blocked
        mode = "sandbox" if gstin == SANDBOX_GSTIN else "live"
        key = f"gst:{gstin}"
        if (hit := db.cache_get(self.engine, key)):
            res = AdapterResult.from_dict(hit[0])
            res.from_cache = True
            return res
        status, body = self._get(f"/v1/gstin/{gstin}", {"include": "profile"})
        res = self._result(status, body, parse_lookup, f"{SOURCE}/v1/gstin/{gstin}", mode)
        if res.ok or res.error == "not_found":      # cache real answers only, never outages
            db.cache_put(self.engine, key, res.as_dict())
        return res

    def pan_verify(self, pan: str, name: str | None = None) -> AdapterResult:
        """GET /v1/pan/{pan}/verify?level=basic: does the PAN exist, and whose is it. Costs 4-6 credits, so it is only ever
        called on demand (or for a vendor with no GSTIN), never automatically. Cached locally for 24 hours."""
        if (blocked := self._guard()):
            return blocked
        key = f"pan:{pan}"
        if (hit := db.cache_get(self.engine, key)):
            res = AdapterResult.from_dict(hit[0])
            res.from_cache = True
            return res
        params = {"level": "basic", **({"name": name} if name else {})}
        status, body = self._get(f"/v1/pan/{pan}/verify", params)
        res = self._result(status, body, parse_pan, f"{SOURCE}/v1/pan/{pan}/verify", "live")
        if res.ok:
            db.cache_put(self.engine, key, res.as_dict())
        return res

    def returns(self, gstin: str, fy: str) -> AdapterResult:
        if (blocked := self._guard()):
            return blocked
        key = f"gst-returns:{gstin}:{fy}"
        if (hit := db.cache_get(self.engine, key)):
            res = AdapterResult.from_dict(hit[0])
            res.from_cache = True
            return res
        status, body = self._get(f"/v1/gstin/{gstin}/returns", {"fy": fy})
        res = self._result(status, body, parse_returns, f"{SOURCE}/v1/gstin/{gstin}/returns?fy={fy}", "live")
        if res.ok:
            db.cache_put(self.engine, key, res.as_dict())
        return res


class RecordedGst:
    """Replays responses captured earlier (fixtures/gst/<GSTIN>.json). Mode `recorded`: shown as such,
    and never satisfies approval for a real vendor. Used by simulated test cases and the tests."""

    def __init__(self, fixtures: dict[str, dict] | None = None, directory: Path | None = None):
        self.fixtures = dict(fixtures or {})
        self.directory = directory if directory is not None else config.FIXTURE_DIR / "gst"

    def _load(self, gstin: str) -> dict | None:
        if gstin in self.fixtures:
            return self.fixtures[gstin]
        p = self.directory / f"{gstin}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def has(self, gstin: str) -> bool:
        return self._load(gstin) is not None

    def lookup(self, gstin: str) -> AdapterResult:
        raw = self._load(gstin)
        if raw is None:
            return AdapterResult(False, source=SOURCE, mode="recorded", error="not_configured",
                                 message="No recorded response exists for this GSTIN (capture fixtures with scripts/capture_fixtures.py).")
        if raw.get("success") is False:
            return AdapterResult(False, source=SOURCE, mode="recorded", raw=raw, error="not_found",
                                 message=raw.get("error", "Not registered."))
        return AdapterResult(True, parse_lookup(raw), SOURCE, "recorded", fetched_at=raw.get("_fetched_at", now_iso()),
                             raw=raw, ref=f"recorded {gstin}")

    def pan_verify(self, pan: str, name: str | None = None) -> AdapterResult:
        return AdapterResult(False, source=SOURCE, mode="recorded", error="not_configured", message="PAN verify is not recorded.")

    def returns(self, gstin: str, fy: str) -> AdapterResult:
        raw = (self._load(gstin) or {}).get("_returns", {}).get(fy)
        if raw is None:
            return AdapterResult(False, source=SOURCE, mode="recorded", error="not_configured", message="No recorded returns.")
        return AdapterResult(True, parse_returns(raw), SOURCE, "recorded", raw=raw, ref=f"recorded returns {gstin} {fy}")
