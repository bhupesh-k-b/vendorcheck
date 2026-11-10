"""Bank account penny drop via Cashfree Bank Account Verification v2 (sync).

Docs: https://www.cashfree.com/docs/api-reference/vrs/v2/bav-v2/bank-account-verification-sync-v2.md
POST {base}/bank-account/sync  headers x-client-id / x-client-secret  body {bank_account, ifsc, name?, phone?}
Response: account_status VALID|INVALID, account_status_code, name_at_bank, name_match_score, name_match_result.

Sandbox only answers for Cashfree's published test accounts, so a sandbox answer is mode `sandbox` and
NEVER verifies a real vendor. Without keys this adapter reports `not_configured` and bank checks go to
two-person finance confirmation."""
import httpx

from .. import config
from .base import AdapterResult

BASES = {"sandbox": "https://sandbox.cashfree.com/verification", "production": "https://api.cashfree.com/verification"}
SOURCE = "cashfree.com BAV v2"


class CashfreeBav:
    def __init__(self, client_id: str | None = None, secret: str | None = None, env: str | None = None,
                 client: httpx.Client | None = None):
        self.client_id = config.cashfree_id() if client_id is None else client_id
        self.secret = config.cashfree_secret() if secret is None else secret
        self.env = env or config.cashfree_env()
        self.client = client or httpx.Client(timeout=30)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.secret)

    @property
    def mode(self) -> str:
        return "live" if self.env == "production" else "sandbox"

    def verify(self, account: str, ifsc: str, name: str | None = None) -> AdapterResult:
        if not self.configured:
            return AdapterResult(False, source=SOURCE, mode=self.mode, error="not_configured",
                                 message="Cashfree keys are not set, so there is no live penny drop.")
        body = {"bank_account": account, "ifsc": ifsc}
        if name:
            body["name"] = name
        try:
            r = self.client.post(f"{BASES.get(self.env, BASES['sandbox'])}/bank-account/sync", json=body,
                                 headers={"x-client-id": self.client_id, "x-client-secret": self.secret})
        except httpx.TimeoutException:
            return AdapterResult(False, source=SOURCE, mode=self.mode, error="timeout", message="Cashfree timed out.")
        except httpx.HTTPError as e:
            return AdapterResult(False, source=SOURCE, mode=self.mode, error="network", message=str(e))
        try:
            d = r.json()
        except ValueError:
            d = {}
        if r.status_code in (401, 403):
            return AdapterResult(False, source=SOURCE, mode=self.mode, raw=d, error="auth", message="Cashfree rejected the keys.")
        if r.status_code in (429, 500, 502):
            return AdapterResult(False, source=SOURCE, mode=self.mode, raw=d, error="upstream", message="Cashfree is busy or down.")
        if r.status_code >= 400:
            return AdapterResult(False, source=SOURCE, mode=self.mode, raw=d, error="bad_format",
                                 message=d.get("message", "Cashfree rejected the request."))
        valid = d.get("account_status") == "VALID"
        fields = {"account_status": d.get("account_status", ""), "status_code": d.get("account_status_code", ""),
                  "name_at_bank": d.get("name_at_bank") or "", "name_match_score": d.get("name_match_score"),
                  "bank_name": d.get("bank_name") or "", "valid": valid}
        return AdapterResult(True, fields, SOURCE, self.mode, raw=d, ref=f"cashfree reference_id {d.get('reference_id', '')}")
