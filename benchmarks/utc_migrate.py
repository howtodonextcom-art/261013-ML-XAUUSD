"""Derive / inspect / roll back the UTC-keyed M1 store (docs/research/M1_ENTRY_V2_AMENDMENTS.md A12).

  python benchmarks/utc_migrate.py            # migrate (idempotent; backs up the manifest first) and print the report
  python benchmarks/utc_migrate.py --rollback # remove ONLY the derived kind (files are moved aside, legacy untouched)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/gateway", "services/intelligence"):
    sys.path.insert(0, str(ROOT / p))
from xau_gateway import utcstore  # noqa: E402
from xau_gateway.identity import load_source_config  # noqa: E402
from xau_gateway.storage import Store  # noqa: E402


def main() -> int:
    cfg = load_source_config()
    server, symbol = cfg["expected"]["server"], cfg.get("symbol_hint", "XAUUSD")
    st = Store(ROOT / "data" / "store")
    if "--rollback" in sys.argv:
        print(json.dumps(utcstore.rollback_utc(st), indent=1))
        return 0
    print(json.dumps(utcstore.migrate(st, server, symbol), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
