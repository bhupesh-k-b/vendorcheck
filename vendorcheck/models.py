"""Database tables (SQLModel on SQLite). Versions are immutable: a correction creates a new Version."""
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Case(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    token: str = Field(index=True, unique=True)          # vendor portal link: /v/<token>
    display_name: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    status: str = "running"                              # running | pending | approved | rejected
    waiting_on: str = ""                                 # vendor | procurement | finance | system
    reason: str = ""
    vendor_code: str = ""                                # set on approval, or the vendor this case updates
    update_of: str = ""                                  # R01: vendor code this submission updates
    decided_at: Optional[datetime] = None
    current_version: int = 1
    explanation: str = ""                                # "Approved with an explanation" text
    sim: bool = False                                    # a simulated test case on a fictional vendor
    decision: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class Version(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(index=True)
    number: int = 1
    created_at: datetime = Field(default_factory=utcnow)
    created_by: str = "staff"                            # staff | vendor
    declared: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))   # typed fields
    files: list[Any] = Field(default_factory=list, sa_column=Column(JSON))           # {sha256,name,mime,size}
    changes: list[Any] = Field(default_factory=list, sa_column=Column(JSON))         # diff vs previous version
    profile: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))    # merged working values (after Read)


class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(index=True)
    version_id: int = Field(index=True)
    number: int = 1
    trigger: str = "submission"
    status: str = "running"                              # running | done | error
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
    sim: bool = False


class StageEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(index=True)
    idx: int = 0
    key: str = ""
    name: str = ""
    status: str = "queued"                               # queued | running | passed | flagged | failed
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    summary: str = ""
    checks: list[Any] = Field(default_factory=list, sa_column=Column(JSON))


class Evidence(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(index=True)
    version_id: int = 0
    run_id: int = 0
    field: str = ""                                      # e.g. gst.status, legal_name
    value: str = ""
    source: str = ""
    mode: str = ""                                       # declared|document|computed|dataset|live|assisted|sandbox|recorded|derived_from_gst
    captured_at: datetime = Field(default_factory=utcnow)
    ref: str = ""                                        # file+page, API response id, screenshot
    side: str = ""                                       # declared | document | government (for the evidence table)
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    captured_by: str = ""
    approved_by: str = ""                                # assisted evidence counts only once a second person approves


class Task(SQLModel, table=True):
    """One open item with exactly one owner. Staff resolve it; a second person must approve (R22)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(index=True)
    version_id: int = 0
    key: str = ""                                        # stable key, e.g. "R16" or "R12"
    rule_id: str = ""
    owner: str = ""                                      # vendor | procurement | finance | system
    kind: str = "confirm"                                # confirm | evidence | vendor | retry
    title: str = ""
    detail: str = ""
    status: str = "open"                                 # open | resolved | approved | declined | superseded
    outcome: str = ""                                    # confirmed | reject
    method: str = ""
    note: str = ""
    resolved_by: str = ""
    resolved_at: Optional[datetime] = None
    approved_by: str = ""
    approved_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class Audit(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(index=True)
    at: datetime = Field(default_factory=utcnow)
    actor: str = ""
    action: str = ""
    detail: str = ""


class VendorMaster(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    vendor_code: str = Field(index=True, unique=True)
    pan: str = Field(index=True, default="")
    legal_name: str = ""
    status: str = "active"                               # active | blocked
    case_id: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    record: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class KV(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str = ""


class ExtractionCache(SQLModel, table=True):
    key: str = Field(primary_key=True)                   # "<sha256>:<kind>"
    created_at: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class AdapterCache(SQLModel, table=True):
    key: str = Field(primary_key=True)                   # e.g. "gst:33AAACZ4322M1ZA"
    fetched_at: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
