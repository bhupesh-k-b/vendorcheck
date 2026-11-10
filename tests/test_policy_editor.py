"""Editing the policy from the Settings page: validation, live effect, persistence, restore. Never touches the real policy.yaml."""
import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from tests.conftest import make_ctx
from vendorcheck import config, policy
from vendorcheck.web.app import create_app


def full_form(**over):
    f = {"name_match_threshold": "85", "require_documents": "always", "require_commercial_setup": "on", "msme_payment_terms_days": "30",
         "filing_gap_months": "3", "reverify_days": "180", "recheck_company_status": "20", "recheck_advisory": "60",
         "blocklist_pans": "ABCDE1234F\nPQRSX9876Z", "blocklist_accounts": "000000000000"}
    for k, (_, _, allowed) in policy.REQUIREMENTS.items():
        f[f"req__{k}__{allowed[0]}"] = "on"
    f.update(over)
    return f


def test_valid_form_updates_every_setting():
    new, errors = policy.policy_from_form(full_form(), policy.load_policy())
    assert errors == []
    assert new["name_match_threshold"] == 85 and new["require_documents"] == "always" and new["msme_payment_terms_days"] == 30
    assert new["rename_requires_person"] is False                       # an unticked switch is off
    assert new["recheck_days"] == {"company_status": 20, "advisory": 60} and new["reverify_days"] == 180
    assert new["blocklist"] == {"pans": ["ABCDE1234F", "PQRSX9876Z"], "accounts": ["000000000000"]}
    assert new["requirements"]["gst_registration"] == ["live"]


def test_invalid_values_keep_the_current_setting_and_are_reported():
    cur = policy.load_policy()
    new, errors = policy.policy_from_form(full_form(name_match_threshold="12", msme_payment_terms_days="abc", blocklist_pans="NOTAPAN"), cur)
    assert new["name_match_threshold"] == cur["name_match_threshold"] and new["msme_payment_terms_days"] == cur["msme_payment_terms_days"]
    assert any("Name match threshold" in e for e in errors) and any("MSME" in e for e in errors) and any("NOTAPAN" in e for e in errors)
    assert "NOTAPAN" not in new["blocklist"]["pans"]


def test_every_requirement_keeps_at_least_one_kind_of_evidence():
    form = full_form()
    form.pop("req__bank_account__live")
    cur = policy.load_policy()
    new, errors = policy.policy_from_form(form, cur)
    assert new["requirements"]["bank_account"] == cur["requirements"]["bank_account"]
    assert any("Bank account" in e for e in errors)


@pytest.fixture
def editor(monkeypatch):
    path = Path(tempfile.mkdtemp()) / "policy.yaml"
    monkeypatch.setattr(config, "POLICY_PATH", path)
    ctx = make_ctx(url=f"sqlite:///{tempfile.mkdtemp()}/p.db")
    ctx.sim, ctx.pacing = False, 0
    return TestClient(create_app(ctx)), ctx, path


def test_settings_page_shows_the_policy_controls(editor):
    c, _, _ = editor
    html = c.get("/settings").text
    for needle in ('name="name_match_threshold"', 'name="require_documents"', 'name="req__bank_account__live"', 'name="blocklist_pans"', "Save policy", "Restore defaults"):
        assert needle in html, needle


def test_saving_applies_immediately_and_is_written_to_the_policy_file(editor):
    c, ctx, path = editor
    r = c.post("/settings/policy", data=full_form(), follow_redirects=False)
    assert r.status_code == 303
    assert ctx.policy["name_match_threshold"] == 85 and ctx.policy["require_documents"] == "always"       # the running engine sees it now
    saved = yaml.safe_load(path.read_text())
    assert saved["name_match_threshold"] == 85 and saved["blocklist"]["pans"] == ["ABCDE1234F", "PQRSX9876Z"]
    assert "Last changed by" in c.get("/settings").text


def test_restore_defaults_returns_every_setting_to_its_default(editor):
    c, ctx, path = editor
    c.post("/settings/policy", data=full_form(), follow_redirects=False)
    c.post("/settings/policy/restore", follow_redirects=False)
    assert ctx.policy["name_match_threshold"] == policy.DEFAULTS["name_match_threshold"]
    assert yaml.safe_load(path.read_text())["require_documents"] == policy.DEFAULTS["require_documents"]
