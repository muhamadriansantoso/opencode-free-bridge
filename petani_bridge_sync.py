#!/usr/bin/env python3
# EXSALA HERMES MOD · powered by Gienetic
"""PetaniProxy -> opencode-free-bridge egress pool sync (probe-gated).

Samples candidates from petani's residential output, CONNECT-probes each
through api.ipify.org, pushes only live proxies into the bridge pool
(POST /api/proxy, no restart). Gateway 8888 always appended as insurance.
"""

import json
import random
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timezone

PETANI_FILE = Path.home() / "Project/petani-proxy/output/webshare_residential.txt"
BRIDGE = "http://127.0.0.1:20129"
LOG = Path.home() / ".opencode-free-bridge/petani-sync.log"
SAMPLE = 150      # candidates sampled per run
MAX_LIVE = 40    # live entries pushed (plus gateway)
GATEWAY = "http://127.0.0.1:8888"
PROBE_URL = "https://api.ipify.org"
PROBE_TIMEOUT = 8
URL_RE = re.compile(r"^https?://[^\s:@/]+:[^\s:@/]+@[^\s:/]+:\d+$")

def log(msg):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a") as f:
        f.write(f"[{stamp}] {msg}\n")
    print(msg)

def probe(url):
    """Return url if a CONNECT tunnel + HTTPS GET works, else None."""
    try:
        req = urllib.request.Request(PROBE_URL)
        handler = urllib.request.ProxyHandler({"http": url, "https": url})
        opener = urllib.request.build_opener(handler)
        with opener.open(req, timeout=PROBE_TIMEOUT) as r:
            if r.status == 200:
                return url
    except Exception:
        pass
    return None

def post(path, payload):
    req = urllib.request.Request(
        BRIDGE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def main():
    if not PETANI_FILE.exists():
        log(f"ERROR amunisi tidak ada: {PETANI_FILE}")
        return 1

    lines = [l.strip() for l in PETANI_FILE.read_text().splitlines()
             if l.strip() and URL_RE.match(l.strip())]
    if not lines:
        log("ERROR tidak ada kandidat valid")
        return 1

    random.shuffle(lines)
    candidates = lines[:SAMPLE]

    live = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(probe, u): u for u in candidates}
        for f in as_completed(futures):
            r = f.result()
            if r:
                live.append(r)

    entries = [{"id": f"resi{i}", "label": f"petani-resi-{i}", "url": u, "enabled": True}
               for i, u in enumerate(live[:MAX_LIVE])]
    entries.append({"id": "gw", "label": "petani-gateway", "url": GATEWAY, "enabled": True})

    result = post("/api/proxy", {"entries": entries})
    pool = result.get("pool", {})
    log(f"probe {len(candidates)} kandidat -> hidup {len(live)}; "
        f"push {len(entries)} entry -> pool {pool.get('enabled', '?')}/{pool.get('size', '?')}")

    try:
        with urllib.request.urlopen(BRIDGE + "/health", timeout=10) as r:
            h = json.loads(r.read())
        p = h["egress"]["proxy"]["pool"]
        log(f"health: ready={p.get('ready')} cooling={p.get('cooling')} size={p.get('size')}")
    except Exception as e:
        log(f"WARN health check gagal: {e}")
        return 0

    # Auto-unquarantine: kalau pool sehat, lepaskan quarantine koneksi ocb
    # di kedua 9router (429 storm bikin pro mengkarantina koneksi dgn
    # backoffLevel tinggi; tanpa ini koneksi di-skip walau pool sudah pulih).
    if p.get("ready", 0) >= 10:
        import sqlite3
        for db_path in ("/home/mrians/Project/9router-pro/data/db/data.sqlite",
                        "/home/mrians/Project/9router/data/db/data.sqlite"):
            try:
                conn = sqlite3.connect(db_path)
                rows = conn.execute(
                    "SELECT id, data FROM providerConnections WHERE data LIKE '%127.0.0.1:20129%'"
                ).fetchall()
                for cid, data in rows:
                    d = json.loads(data)
                    quarantined = (d.get("testStatus") != "active" or d.get("backoffLevel", 0) > 0
                                   or any(k.startswith("modelLock") for k in d))
                    if not quarantined:
                        continue
                    for k in [k for k in d if k.startswith("modelLock")]:
                        d.pop(k)
                    d["testStatus"] = "active"; d["backoffLevel"] = 0; d["errorCode"] = None
                    conn.execute("UPDATE providerConnections SET isActive=1, data=? WHERE id=?",
                                 (json.dumps(d), cid))
                    conn.commit()
                    log(f"unquarantine {db_path.split('/')[-3]}: {cid[:8]}")
            except Exception as e:
                log(f"WARN unquarantine gagal ({db_path.split('/')[-3]}): {e}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
