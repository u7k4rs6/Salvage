import type { RecordedLedgerEntry } from "./types";

/**
 * The chain check, recomputed in the browser over the fixture.
 *
 * This is the same computation `salvage ledger verify` and `scripts/verify_ledger.py` do, against
 * the same bytes: the recording keeps `payload_json` as the exact string the entry's hash commits
 * to, so nothing here re-serialises anything and no float formatting or key order has to be
 * agreed on.
 *
 * The pre-image, from salvage/ledger.py:
 *
 *   sha256(seq \n ts \n kind \n ref_type \n ref_id \n payload_json \n prev_hash \n)
 *
 * with every field followed by its own newline. `canonical_json` escapes every control character,
 * so a newline cannot appear inside a field and the separator cannot be forged from within one.
 *
 * What this proves is what the Ledger page already says it proves: that the record has not been
 * altered since it was written. It does not prove the process wrote the truth.
 */

export interface VerifyResult {
  ok: boolean;
  entries: number;
  headHash: string | null;
  brokenSeq: number | null;
  detail: string;
}

const encoder = new TextEncoder();

async function sha256Hex(input: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(input));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function verifyChain(
  entries: RecordedLedgerEntry[],
  genesisHash: string,
): Promise<VerifyResult> {
  let prevHash = genesisHash;
  let expectedSeq = 1;

  for (const entry of entries) {
    if (entry.seq !== expectedSeq) {
      return {
        ok: false,
        entries: entries.length,
        headHash: null,
        brokenSeq: entry.seq,
        detail: `expected sequence ${expectedSeq}, found ${entry.seq}`,
      };
    }
    if (entry.prev_hash !== prevHash) {
      return {
        ok: false,
        entries: entries.length,
        headHash: null,
        brokenSeq: entry.seq,
        detail: "prev_hash does not match the previous entry's hash",
      };
    }
    const preimage =
      `${entry.seq}\n${entry.ts}\n${entry.kind}\n${entry.ref_type}\n` +
      `${entry.ref_id}\n${entry.payload_json}\n${entry.prev_hash}\n`;
    const recomputed = await sha256Hex(preimage);
    if (recomputed !== entry.hash) {
      return {
        ok: false,
        entries: entries.length,
        headHash: null,
        brokenSeq: entry.seq,
        detail: "stored hash does not match the recomputed hash",
      };
    }
    prevHash = entry.hash;
    expectedSeq += 1;
  }

  return {
    ok: true,
    entries: entries.length,
    headHash: prevHash,
    brokenSeq: null,
    detail: "ok",
  };
}

/** What the Ledger page says under its title, repeated here for the same reason. */
export const PROVES =
  "This chain proves the record has not been altered after it was written: every entry commits " +
  "to the one before it, and changing any byte of any entry breaks verification from that point " +
  "on. It does not prove the process wrote the truth. A wrong decision, faithfully recorded, " +
  "verifies perfectly.";
