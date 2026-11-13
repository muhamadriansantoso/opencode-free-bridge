#!/usr/bin/env python3
# EXSALA HERMES MOD · powered by Gienetic
"""Standalone unquarantine untuk koneksi opencode-bridge di kedua 9router.

Jalan tiap 5 menit via systemd user timer. Kalau bridge pool punya entry
siap (bridge sehat), buang quarantine koneksi 20129 — supaya 429 sesaat
di satu model tidak meng-coret seluruh jalur bridge berjam-jam.
"""

import json
import sqlite3
import urllib.request

BRIDGE = "http://127.0.0.1:20129/health"
DBS = ("/home/mrians/Project/9router-pro/data/db/data.sqlite",
       "/home/mrians/Project/9router/data/db/data.sqlite")

def main():
    try:
        with urllib.request.urlopen(BRIDGE, timeout=10) as r:
            p = json.loads(r.read())["egress"]["proxy"]["pool"]
        if p.get("ready", 0) < 1:
            print(f"bridge pool tidak siap (ready={p.get('ready')}) — skip")
            return
    except Exception as e:
        print(f"bridge tidak terjangkau: {e} — skip")
        return

    for db_path in DBS:
        try:
            conn = sqlite3.connect(db_path)
            changed = 0
            for cid, data in conn.execute(
                "SELECT id, data FROM providerConnections WHERE data LIKE '%127.0.0.1:20129%'"
            ).fetchall():
                d = json.loads(data)
                quarantined = (d.get("testStatus") != "active"
                               or d.get("backoffLevel", 0) > 0
                               or any(k.startswith("modelLock") for k in d))
                if not quarantined:
                    continue
                for k in [k for k in d if k.startswith("modelLock")]:
                    d.pop(k)
                d["testStatus"] = "active"; d["backoffLevel"] = 0; d["errorCode"] = None
                conn.execute("UPDATE providerConnections SET isActive=1, data=? WHERE id=?",
                             (json.dumps(d), cid))
                changed += 1
            conn.commit()
            if changed:
                print(f"{db_path.split('/')[-3]}: {changed} koneksi dibuka")
        except Exception as e:
            print(f"{db_path.split('/')[-3]}: ERROR {e}")

if __name__ == "__main__":
    main()
