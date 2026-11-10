"""Settings read from the environment (.env). Secrets are never logged or rendered."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("VENDORCHECK_DATA", ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
CACHE_DIR = DATA_DIR / "cache"
DB_URL = os.getenv("VENDORCHECK_DB", f"sqlite:///{DATA_DIR / 'vendorcheck.db'}")
POLICY_PATH = Path(os.getenv("VENDORCHECK_POLICY", ROOT / "policy.yaml"))
FIXTURE_DIR = ROOT / "fixtures"
SAMPLES_DIR = ROOT / "samples"
_BUNDLED_IFSC = ROOT / "vendor_data" / "ifsc"          # shipped with the code, so a read-only host still has the bank directory
IFSC_DIR = Path(os.getenv("VENDORCHECK_IFSC_DIR") or (DATA_DIR / "ifsc" if (DATA_DIR / "ifsc" / "IFSC.json").exists() or not (_BUNDLED_IFSC / "IFSC.json").exists() else _BUNDLED_IFSC))
IFSC_PATH = IFSC_DIR / "IFSC.json"
BANKNAMES_PATH = IFSC_DIR / "banknames.json"
IFSC_META_PATH = IFSC_DIR / "meta.json"


# Keys a visitor pastes into Settings. Held in this process only: never written to disk, never rendered back.
_RUNTIME: dict[str, str] = {}
RUNTIME_KEYS = ("GSTINAPI_KEY", "GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEYS", "READER_PROVIDER")


def set_runtime(values: dict[str, str]) -> None:
    for k, v in values.items():
        if k in RUNTIME_KEYS:
            if v.strip():
                _RUNTIME[k] = v.strip()
            else:
                _RUNTIME.pop(k, None)


def clear_runtime() -> None:
    _RUNTIME.clear()


def has_runtime() -> bool:
    return bool(_RUNTIME)


def keys_enabled() -> bool:
    """A deployment can switch the key form off with ALLOW_USER_KEYS=0."""
    return os.getenv("ALLOW_USER_KEYS", "1").strip() != "0"


def env(name: str, default: str = "") -> str:
    if name in _RUNTIME:
        return _RUNTIME[name]
    return os.getenv(name, default).strip()


def gemini_key() -> str: return env("GEMINI_API_KEY")
def gemini_model() -> str: return env("GEMINI_MODEL", "gemini-3.8-flash")
def openrouter_keys() -> list[str]:
    """OPENROUTER_API_KEYS (comma separated, tried in order) plus the single OPENROUTER_API_KEY as a last resort."""
    keys = [k.strip() for k in env("OPENROUTER_API_KEYS").split(",") if k.strip()]
    single = env("OPENROUTER_API_KEY")
    return keys + ([single] if single and single not in keys else [])
def openrouter_key() -> str: return (openrouter_keys() or [""])[0]
def openrouter_model() -> str: return env("OPENROUTER_MODEL", "google/gemini-3.8-flash")
def reader_quality() -> str:
    """READER_QUALITY=high (default): AI cleans scanned names, reads low-confidence pages by vision, and breaks OCR ties.
    economy: AI only for pages the rules cannot settle."""
    return env("READER_QUALITY", "high").lower()
def groq_key() -> str: return env("GROQ_API_KEY")
def groq_model() -> str: return env("GROQ_MODEL", "openai/gpt-oss-120b")
def groq_vision_model() -> str: return env("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
def reader_provider() -> str:
    """READER_PROVIDER=groq|openrouter|gemini; default: the first one that has a key (groq, openrouter, gemini)."""
    return env("READER_PROVIDER") or ("groq" if groq_key() else "openrouter" if openrouter_key() else "gemini")
def gstin_key() -> str: return env("GSTINAPI_KEY")
def cashfree_id() -> str: return env("CASHFREE_CLIENT_ID")
def cashfree_secret() -> str: return env("CASHFREE_CLIENT_SECRET")
def cashfree_env() -> str: return env("CASHFREE_ENV", "sandbox")
def inline_runs() -> bool:
    """Serverless hosts freeze background threads once the response is sent, so a run executes inside the request instead."""
    return env("VENDORCHECK_INLINE") == "1"
def pacing_seconds() -> float: return float(env("VENDORCHECK_PACING_MS", "0") or 0) / 1000.0


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOAD_DIR, CACHE_DIR, IFSC_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
