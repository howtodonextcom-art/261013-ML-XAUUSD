"""Prints the expected-identity block (server + hashed account ref) for configs/source.json. Read-only. Usage: pin_identity.py <terminal64.exe>"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "gateway"))
import MetaTrader5 as mt5
from xau_gateway.mt5_source import short_hash
assert mt5.initialize(path=sys.argv[1]), mt5.last_error()
a = mt5.account_info()
print({"server": a.server, "build": None, "account_ref": short_hash(a.login)})
mt5.shutdown()
