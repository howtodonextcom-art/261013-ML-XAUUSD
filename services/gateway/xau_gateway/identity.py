"""Terminal identity: ONE implementation shared by the live source and the backfill (audit risk F).
The account number is never logged or stored in clear: only an 8-hex SHA-256 prefix ('account_ref') is used."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def short_hash(x) -> str:
    return hashlib.sha256(str(x).encode()).hexdigest()[:8]


def load_source_config() -> dict:
    p = ROOT / "configs" / "source.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def verify_identity(ti, ai, terminal_path: str, expected: dict | None) -> str | None:
    """Return None when the connected terminal matches the pinned identity, else a human-readable mismatch reason."""
    exp = expected or {}
    if ti is None:
        return "terminal_info unavailable"
    if Path(ti.path).resolve() != Path(terminal_path).resolve().parent:
        return f"terminal path {ti.path} != configured {Path(terminal_path).parent}"
    if exp.get("server") and (ai is None or ai.server != exp["server"]):
        return f"server {getattr(ai, 'server', None)} != expected {exp['server']}"
    if exp.get("build") and ti.build != exp["build"]:
        return f"build {ti.build} != expected {exp['build']}"
    if exp.get("account_ref") and ai is not None and short_hash(ai.login) != exp["account_ref"]:
        return "account identity differs from the pinned account_ref"
    return None
