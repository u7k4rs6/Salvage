#!/usr/bin/env python3
"""Verify a Salvage ledger export offline.

Deliberately self-contained: standard library only, no import from the salvage package, its own
copy of the genesis constant and the hash rule. A reviewer can read this file, check it against
docs/03_SECURITY_AND_ACCESS.md section 8, and run it against a JSONL export without trusting
anything Salvage ships.

Usage:  python3 scripts/verify_ledger.py data/ledger.jsonl
Exit 0 if the chain is intact, 1 if it is broken.
"""

from __future__ import annotations

import hashlib
import json
import sys

GENESIS_HASH = "e033221f96520f784ef136e1ba52ae6b04cba31331157e223f1c97e64ae59524"


def entry_hash(entry: dict) -> str:
    digest = hashlib.sha256()
    for field in ("seq", "ts", "kind", "ref_type", "ref_id", "payload_json", "prev_hash"):
        digest.update(str(entry[field]).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def main(path: str) -> int:
    prev_hash, expected_seq, count = GENESIS_HASH, 1, 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("type") == "salvage.ledger.export":
                # Informational header. The constant above is the authority, not the file.
                if entry.get("genesis_hash") != GENESIS_HASH:
                    print("export declares a different genesis hash", file=sys.stderr)
                    return 1
                continue
            if int(entry["seq"]) != expected_seq:
                print(f"broken at sequence {entry['seq']}: expected {expected_seq}")
                return 1
            if entry["prev_hash"] != prev_hash:
                print(f"broken at sequence {entry['seq']}: prev_hash mismatch")
                return 1
            if entry_hash(entry) != entry["hash"]:
                print(f"broken at sequence {entry['seq']}: hash mismatch")
                return 1
            prev_hash, expected_seq, count = entry["hash"], expected_seq + 1, count + 1
    print(f"Chain intact, {count} entries, head hash {prev_hash[:12]}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
