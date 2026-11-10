"""Capture REAL gstinapi.in responses once, into fixtures/gst/<GSTIN>.json, so tests and simulated cases can
replay them (mode `recorded`) at zero credits. Spends about 4 credits. Never writes anything it did not receive.

    .venv/bin/python scripts/capture_fixtures.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vendorcheck import config, db  # noqa: E402
from vendorcheck.adapters.gst import GstApi  # noqa: E402

TARGETS = {
    "33AAACZ4322M1ZA": "Zoho Corporation Private Limited (happy path)",
    "33AABCZ7092H1Z3": "Zoho Payment Technologies Private Limited (E3 look-alike)",
    "24AAACR4849R1ZR": "Tata Consultancy Services, regular Gujarat GSTIN (E2 correction)",
    "33AADCD4946L1ZH": "Eternal Limited (E1)",
    "29AAACI4798L1ZU": "Infosys Limited",
}


def main():
    if not config.gstin_key():
        sys.exit("GSTINAPI_KEY is not set in .env. Nothing captured.")
    engine = db.make_engine()
    gst = GstApi(engine)
    out = config.FIXTURE_DIR / "gst"
    out.mkdir(parents=True, exist_ok=True)
    for gstin, why in TARGETS.items():
        res = gst.lookup(gstin)
        if not res.ok:
            print(f"SKIP {gstin} ({why}): {res.error} {res.message}")
            continue
        raw = dict(res.raw, _fetched_at=res.fetched_at, _captured_mode=res.mode)
        (out / f"{gstin}.json").write_text(json.dumps(raw, indent=2))
        f = res.fields
        print(f"OK   {gstin}: {f['legal_name']} / {f['status']} / {f['taxpayer_type']} (credits left: {raw.get('credits_remaining')})")


if __name__ == "__main__":
    main()
