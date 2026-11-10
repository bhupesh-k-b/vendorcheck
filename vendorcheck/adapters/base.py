"""Every adapter returns the same shape: {fields..., source, mode, fetched_at, raw}."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Why a source could not answer. None of these is ever treated as a pass (R20).
UNREACHABLE = {"not_configured", "simulated_outage", "upstream", "timeout", "auth", "credits", "rate_limited", "network"}


@dataclass
class AdapterResult:
    ok: bool
    fields: dict = field(default_factory=dict)
    source: str = ""
    mode: str = ""            # live | sandbox | recorded | assisted | dataset
    fetched_at: str = field(default_factory=now_iso)
    raw: dict | None = None
    error: str = ""           # "" | not_found | bad_format | one of UNREACHABLE
    message: str = ""
    ref: str = ""             # API response id / URL
    from_cache: bool = False

    @property
    def unreachable(self) -> bool:
        return self.error in UNREACHABLE

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AdapterResult":
        return cls(**d)
