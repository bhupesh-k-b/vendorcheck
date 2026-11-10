"""Stores uploaded files by SHA-256 (immutable), and small shared helpers (audit log)."""
import hashlib
import mimetypes
import re
from pathlib import Path

from sqlmodel import Session

from . import config
from .models import Audit

ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp", ".tif", ".tiff"}


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]", "_", Path(name or "upload").name)[:120] or "upload"


def store_bytes(data: bytes, name: str) -> dict:
    """Save to uploads/<sha256>/<name>; return the file record used on a Version."""
    config.ensure_dirs()
    sha = hashlib.sha256(data).hexdigest()
    name = safe_name(name)
    d = config.UPLOAD_DIR / sha
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    if not p.exists():
        p.write_bytes(data)
    mime = mimetypes.guess_type(name)[0] or ("application/pdf" if data[:4] == b"%PDF" else "application/octet-stream")
    if name.lower().endswith((".heic", ".heif")):
        mime = "image/heic"
    return {"sha256": sha, "name": name, "mime": mime, "size": len(data), "path": str(p)}


def allowed(name: str) -> bool:
    return Path(name).suffix.lower() in ALLOWED


def audit(s: Session, case_id: int, actor: str, action: str, detail: str = "") -> None:
    s.add(Audit(case_id=case_id, actor=actor, action=action, detail=detail))
    s.commit()
