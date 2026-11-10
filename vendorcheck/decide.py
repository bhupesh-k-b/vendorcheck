"""Decide: a PURE function. (checks, task resolutions, policy, today) -> status, open items, conditions.

No database, no network, no model. The model never decides a status.

Gates (brief section 9):
  Rejected  any reject outcome, or a reviewer-confirmed fraud.
  Pending   any blocking check not passed. Each open item has exactly one owner.
  Approved  otherwise; open advisories become conditions, each with a re-check date.
Guardrails: nobody approves their own resolution (R22); urgency never activates a vendor (there is no override)."""
from datetime import date, timedelta
from typing import Any

from .rules import BLOCKING, NOTE, PASS, REJECT, OWNER_LABEL


def _task_for(tasks: list[dict], key: str) -> dict | None:
    live = [t for t in tasks if t["key"] == key and t["status"] != "superseded"]
    return live[-1] if live else None


def _valid_second_approval(t: dict) -> bool:
    """R22: approved by someone other than the resolver."""
    return t["status"] == "approved" and bool(t.get("approved_by")) and t["approved_by"] != t.get("resolved_by")


def decide(checks: list[dict], tasks: list[dict], policy: dict, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    accepted = policy["requirements"]
    open_items: list[dict] = []
    explanations: list[dict] = []
    conditions: list[dict] = []
    rejected: dict | None = None

    for c in checks:
        res, key = c["result"], c["key"]
        task = _task_for(tasks, key)

        # A second-person-approved rejection ("not our account", "fraud") ends the case.
        if task and _valid_second_approval(task) and task.get("outcome") == "reject":
            rejected = rejected or {"rule": c["rule"], "reason": f"{c['name']}: rejected by {task['resolved_by']} and {task['approved_by']}"
                                    + (f" ({task['note']})" if task.get("note") else "")}
            continue

        if res == REJECT:
            rejected = rejected or {"rule": c["rule"], "reason": c["reason"], "reapply": bool(c.get("reapply")), "key": key}
            continue

        # Evidence from the wrong kind of source never satisfies a requirement (e.g. recorded, sandbox).
        if res in (PASS, NOTE) and c.get("requirement") and c["requirement"] in accepted:
            if c.get("mode") and c["mode"] not in accepted[c["requirement"]] and c["requirement"] != "company_status":
                res = "wait"
                c = {**c, "reason": f"{c['mode']} evidence cannot satisfy '{c['requirement'].replace('_', ' ')}' "
                                    f"(policy accepts: {', '.join(accepted[c['requirement']])}).",
                     "owner": c.get("owner") or "system", "title": c.get("title") or "obtain accepted evidence"}

        if res in BLOCKING:
            # A flag owned by the VENDOR is cleared only by the vendor's correction (a new version), never by a reviewer's approval.
            if task and _valid_second_approval(task) and task.get("outcome") == "confirmed" and c.get("kind") != "vendor":
                req = c.get("requirement")
                if req and "assisted" not in accepted.get(req, []):
                    open_items.append(_item(c, task, "needs_resolution",
                                            extra=f"policy does not accept assisted confirmation for {req.replace('_', ' ')}"))
                    continue
                explanations.append({"rule": c["rule"], "text": f"{c['name']}: resolved by {task['resolved_by']} "
                                     f"({task.get('method') or 'manual check'}), approved by {task['approved_by']}."
                                     + (f" Note: {task['note']}" if task.get("note") else "")})
                continue
            stage = "needs_approval" if task and task["status"] == "resolved" else "needs_resolution"
            open_items.append(_item(c, task, stage))
            continue

        if res == NOTE and c.get("reason") and c["rule"] in ("R12",):
            explanations.append({"rule": c["rule"], "text": c["reason"]})
        if c.get("condition"):
            days = c.get("recheck_days") or policy["recheck_days"]["advisory"]
            conditions.append({"rule": c["rule"], "text": c["condition"], "recheck_on": (today + timedelta(days=days)).isoformat()})

    # Who is the case "waiting on"? Whoever must act first: vendor, then system (retry), procurement, finance.
    priority = {"vendor": 0, "system": 1, "procurement": 2, "finance": 3}
    open_items.sort(key=lambda it: priority.get(it["owner"], 9))
    owners: dict[str, int] = {}
    for it in open_items:
        owners[it["owner"]] = owners.get(it["owner"], 0) + 1

    if rejected:
        status, waiting_on, reason = "rejected", "", f"Rejected: {rejected['reason']}"
    elif open_items:
        first = open_items[0]
        status, waiting_on = "pending", first["owner"]
        who = OWNER_LABEL.get(first["owner"], first["owner"])
        if first["stage"] == "needs_approval":
            reason = f"Pending: waiting on a second approver to approve ({first['title']})"
        else:
            reason = f"Pending: waiting on {who} to {first['title']}"
        if len(open_items) > 1:
            reason += f" (+{len(open_items) - 1} more open)"
    else:
        status, waiting_on = "approved", ""
        reason = "Approved with an explanation" if explanations else "Approved: every check passed"
        if conditions:
            reason += f", with {len(conditions)} condition{'s' if len(conditions) > 1 else ''}"

    return {"status": status, "waiting_on": waiting_on, "reason": reason, "open_items": open_items,
            "conditions": conditions, "explanations": explanations, "rejected": rejected, "owners": owners,
            "approved_with_explanation": status == "approved" and bool(explanations)}


def _item(c: dict, task: dict | None, stage: str, extra: str = "") -> dict:
    return {"key": c["key"], "rule": c["rule"], "owner": c.get("owner") or "system", "title": c.get("title") or c["name"],
            "detail": c.get("detail") or c.get("reason", ""), "reason": c.get("reason", "") + (f" {extra}" if extra else ""),
            "kind": c.get("kind", "confirm"), "assist": c.get("assist", ""), "stage": stage,
            "task_id": task["id"] if task else None, "vendor_text": c.get("vendor_text", ""),
            "vendor_fields": c.get("vendor_fields", []), "vendor_upload": c.get("vendor_upload", False)}
