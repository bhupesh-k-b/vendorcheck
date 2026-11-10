"""Ctx bundles everything the pipeline needs (engine, policy, adapters, reader), so tests and the
test bench can inject fakes and an isolated in-memory database."""
from dataclasses import dataclass, field
from typing import Any, Callable

from . import config, db
from .adapters import ifsc as ifsc_adapter
from .adapters.cashfree import CashfreeBav
from .adapters.gst import GstApi
from .policy import load_policy
from .reader import GeminiReader, GroqReader, HybridReader, NullReader, OpenRouterReader


@dataclass
class Ctx:
    engine: Any
    policy: dict
    gst: Any                       # GstApi | RecordedGst   (lookup, returns)
    reader: Any                    # Reader
    bav: Any = None                # CashfreeBav | None
    ifsc: Any = ifsc_adapter       # module with lookup()
    pacing: float = 0.0            # seconds each stage stays on screen
    sim: bool = False              # test-bench simulation: never writes to the real vendor master
    enrich: bool = True            # live IFSC branch lookups (display only)
    on_event: Callable[[str], None] | None = None
    extra: dict = field(default_factory=dict)


def build_adapters(engine):
    """(GST adapter, document reader) from the keys currently configured."""
    # Local OCR + rules do the reading. A language model is optional and only reasons over the text of pages the rules cannot settle.
    if config.reader_provider() == "groq" and config.groq_key():
        llm = GroqReader(engine)
    elif config.reader_provider() == "openrouter" and config.openrouter_key():
        llm = OpenRouterReader(engine)
    else:
        llm = GeminiReader(engine) if config.gemini_key() else None
    return GstApi(engine), HybridReader(engine, llm if config.env("READER_AI", "1") != "0" else None)


def default_ctx() -> Ctx:
    engine = db.make_engine()
    gst, reader = build_adapters(engine)
    return Ctx(engine=engine, policy=load_policy(), gst=gst, reader=reader, bav=CashfreeBav(),
               pacing=config.pacing_seconds())


def sources_status(ctx: Ctx) -> list[dict]:
    """Top-bar badges: which sources are live, assisted or not configured."""
    sim_outage = db.get_kv(ctx.engine, "simulate_gst_outage") == "1"
    gst_conf = getattr(ctx.gst, "configured", True)
    out = [
        {"name": "GST", "state": "simulated outage" if sim_outage else ("live" if gst_conf else "not configured"),
         "detail": "gstinapi.in" + (" — SIMULATED outage is on" if sim_outage else "")},
        {"name": "IFSC", "state": "dataset" if ctx.ifsc.dataset_ready() else "not configured", "detail": ctx.ifsc.release_label()},
        {"name": "Reader", "state": "live" if ctx.reader.configured else "not configured", "detail": "Document reader: local OCR and rules" + (", with text analysis only when needed" if getattr(ctx.reader, "llm", None) else "")},
        {"name": "Bank", "state": ("live" if ctx.bav.mode == "live" else "sandbox") if (ctx.bav and ctx.bav.configured) else "assisted",
         "detail": "Cashfree penny drop" if (ctx.bav and ctx.bav.configured) else "Two-person finance confirmation"},
        {"name": "MCA", "state": "assisted", "detail": "No free API: reviewer checks the official site"},
        {"name": "Udyam", "state": "assisted", "detail": "Reviewer checks the official site"},
    ]
    return out
