"""IFSC -> bank and branch, from Razorpay's open dataset (built from RBI lists).

Downloaded at setup (`python -m vendorcheck.adapters.ifsc --download`). The release date is recorded
in meta.json and shown as the evidence source. Optional live branch details come from ifsc.razorpay.com."""
import json
import sys
from functools import lru_cache

import httpx

from .. import config
from .base import AdapterResult, now_iso

RELEASE_URL = "https://github.com/razorpay/ifsc/releases/latest/download/IFSC.json"
BANKNAMES_URL = "https://raw.githubusercontent.com/razorpay/ifsc/master/src/banknames.json"
RELEASE_API = "https://api.github.com/repos/razorpay/ifsc/releases/latest"


def download() -> dict:
    config.ensure_dirs()
    with httpx.Client(follow_redirects=True, timeout=120) as c:
        config.IFSC_PATH.write_bytes(c.get(RELEASE_URL).raise_for_status().content)
        config.BANKNAMES_PATH.write_bytes(c.get(BANKNAMES_URL).raise_for_status().content)
        rel = c.get(RELEASE_API).json()
    meta = {"tag": rel.get("tag_name", "unknown"), "released": (rel.get("published_at") or "")[:10],
            "downloaded": now_iso(), "source": "github.com/razorpay/ifsc (RBI lists)"}
    config.IFSC_META_PATH.write_text(json.dumps(meta))
    load.cache_clear()
    return meta


@lru_cache
def load() -> tuple[dict[str, set[str]], dict[str, str], dict]:
    """Returns (bank code -> set of 6-char branch codes, bank code -> bank name, meta)."""
    if not config.IFSC_PATH.exists():
        return {}, {}, {}
    raw = json.loads(config.IFSC_PATH.read_text())
    banks = {code: {(f"{b:06d}" if isinstance(b, int) else str(b)) for b in branches} for code, branches in raw.items()}
    names = json.loads(config.BANKNAMES_PATH.read_text()) if config.BANKNAMES_PATH.exists() else {}
    meta = json.loads(config.IFSC_META_PATH.read_text()) if config.IFSC_META_PATH.exists() else {}
    return banks, names, meta


def dataset_ready() -> bool:
    return bool(load()[0])


def release_label() -> str:
    meta = load()[2]
    return f"Razorpay IFSC {meta.get('tag', '?')} ({meta.get('released', 'date unknown')})" if meta else "IFSC dataset not downloaded"


def lookup(ifsc: str) -> AdapterResult:
    """R09 existence check against the bundled dataset (mode: dataset)."""
    ifsc = (ifsc or "").strip().upper()
    banks, names, meta = load()
    if not banks:
        return AdapterResult(False, source=release_label(), mode="dataset", error="not_configured",
                             message="The IFSC dataset has not been downloaded (run make setup).")
    code, branch = ifsc[:4], ifsc[5:]
    ok = code in banks and branch in banks[code]
    fields = {"ifsc": ifsc, "bank_name": names.get(code, ""), "bank_code": code} if ok else {}
    return AdapterResult(ok, fields, source=release_label(), mode="dataset", ref=f"IFSC dataset {meta.get('tag', '')}",
                         error="" if ok else "not_found",
                         message="" if ok else f"{ifsc} is not in the RBI IFSC list.")


def branch_details(ifsc: str) -> AdapterResult | None:
    """Optional live branch name/city from ifsc.razorpay.com. Failure is silent: it only enriches display."""
    try:
        r = httpx.get(f"https://ifsc.razorpay.com/{ifsc}", timeout=8)
        if r.status_code != 200:
            return None
        d = r.json()
        return AdapterResult(True, {"branch": d.get("BRANCH", ""), "city": d.get("CITY", ""), "bank_name": d.get("BANK", "")},
                             source="ifsc.razorpay.com", mode="live", raw=d, ref=f"https://ifsc.razorpay.com/{ifsc}")
    except Exception:   # noqa: BLE001  enrichment only
        return None


if __name__ == "__main__":
    if "--download" in sys.argv:
        print(download())
    else:
        print(release_label())
