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
IFSC_PATH = DATA_DIR / "ifsc" / "IFSC.json"
BANKNAMES_PATH = DATA_DIR / "ifsc" / "banknames.json"
IFSC_META_PATH = DATA_DIR / "ifsc" / "meta.json"


def env(name: str, default: str = "") -> str:
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
def pacing_seconds() -> float: return float(env("VENDORCHECK_PACING_MS", "0") or 0) / 1000.0


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOAD_DIR, CACHE_DIR, IFSC_PATH.parent):
        d.mkdir(parents=True, exist_ok=True)
