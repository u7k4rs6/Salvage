import { useState } from "react";
import { useApi } from "../lib/useApi";
import { post } from "../lib/api";
import { useStream } from "../lib/useStream";
import {
  Cell,
  Code,
  Disclosure,
  Empty,
  ErrorPanel,
  Panel,
  Region,
  Table,
  type Column,
} from "../components/primitives";
import { summarise } from "../components/Timeline";
import { shortHash, timestamp } from "../lib/format";
import type { LedgerPage, VerifyResult } from "../lib/types";
import { PageIntro } from "../components/PageIntro";

const REF_TYPES = ["", "sim_run", "incident", "case", "action", "escalation", "webhook", "control"];

/**
 * The ledger's columns. Sequence is a number and right-aligns; everything else is text the eye
 * reads down the left. A long payload summary is never centred.
 */
const LEDGER_COLUMNS: Column[] = [
  { key: "seq", label: "Seq", align: "num", flex: 0.5 },
  // Sized so a full timestamp and the longest kind each sit on one line at the table's floor.
  { key: "time", label: "Time", align: "text", flex: 1.9 },
  { key: "kind", label: "Kind", align: "text", flex: 2.1 },
  { key: "ref", label: "Reference", align: "text", flex: 2.3 },
  // The summary absorbs the width the others do not need.
  { key: "summary", label: "Summary", align: "text", flex: 2 },
  { key: "hash", label: "Hash", align: "text", flex: 1.2 },
];

export default function LedgerPageView() {
  const [kind, setKind] = useState("");
  const [refType, setRefType] = useState("");
  const [refId, setRefId] = useState("");
  const [cursor, setCursor] = useState(0);
  const [verify, setVerify] = useState<VerifyResult | null>(null);
  const [verifyError, setVerifyError] = useState<unknown>(null);

  const query = new URLSearchParams({ limit: "50", cursor: String(cursor) });
  if (kind) query.set("kind", kind);
  if (refType) query.set("ref_type", refType);
  if (refId) query.set("ref_id", refId);
  const state = useApi<LedgerPage>(`/api/ledger?${query.toString()}`);

  useStream(["ledger.appended"], () => state.reload());

  return (
    <div className="space-y-4">
      <PageIntro
        title="Ledger"
        what="The append-only record of everything the system did, in order, with each entry sealed against the one before it."
        use="Filter by kind or by what an entry refers to. Verify recomputes the whole chain and reports the first entry that does not match. Export writes the same bytes an offline verifier reads."
        shows={[
          ["seq", "position in the chain. They run 1, 2, 3 with no gaps, so a gap is a deleted entry"],
          ["kind", "what happened, such as detect.incident.opened, decide.plan or execute.action.refused"],
          ["hash", "a fingerprint of this entry and of the one before it, so changing any byte of any entry breaks every entry after it"],
          ["Verify", "recomputes every fingerprint from the entries themselves and reports whether the chain is intact"],
        ]}
        caveat="What the chain proves is that the record was not altered after it was written. It does not prove the process wrote the truth: a wrong decision, faithfully recorded, verifies perfectly."
        right={
          <div className="flex gap-2">
            <button
              type="button"
              onClick={async () => {
                setVerifyError(null);
                try {
                  setVerify(await post<VerifyResult>("/api/ledger/verify"));
                } catch (cause) {
                  setVerifyError(cause);
                }
              }}
              className="btn btn-primary focus-ring"
            >
              Verify chain
            </button>
            <a href="/api/ledger/export" className="btn focus-ring">
              Export JSONL
            </a>
          </div>
        }
      />
      {/* The chain's controls and what it proves belong to the page, not to a panel whose only
          body was one paragraph and whose title repeated the page title above it. */}
      {verifyError !== null && (
        <div className="mb-4">
          <ErrorPanel error={verifyError} />
        </div>
      )}

      {verify && (
        <div
          role="status"
          className={`mb-4 flex flex-wrap items-baseline gap-x-4 gap-y-1 rounded-[var(--radius-sm)] border px-4 py-3 text-[length:var(--fs-meta)] ${
            verify.ok
              ? "border-[color:var(--success)] text-[color:var(--success)]"
              : "border-[color:var(--danger)] text-[color:var(--danger)]"
          }`}
        >
          {/* The server's message already opens with the verdict, so the banner shows it once
              rather than prefixing a second copy of the same word. */}
          <span className="dt-mono font-medium">{verify.message}</span>
          <span className="dt-mono text-[color:var(--text-muted)]">
            genesis {shortHash(verify.genesis_hash)}
          </span>
        </div>
      )}

      <Panel title="Entries">
        <div className="mb-3 flex flex-wrap items-end gap-3 text-[length:var(--fs-meta)]">
          <label className="flex flex-col gap-1">
            kind
            <select
              value={kind}
              onChange={(event) => {
                setKind(event.target.value);
                setCursor(0);
              }}
              className="border border-[color:var(--border-strong)] px-2 py-1"
            >
              <option value="">all</option>
              {(state.data?.kinds ?? []).map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            ref type
            <select
              value={refType}
              onChange={(event) => {
                setRefType(event.target.value);
                setCursor(0);
              }}
              className="border border-[color:var(--border-strong)] px-2 py-1"
            >
              {REF_TYPES.map((value) => (
                <option key={value} value={value}>
                  {value || "all"}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            ref id
            <input
              value={refId}
              onChange={(event) => {
                setRefId(event.target.value);
                setCursor(0);
              }}
              placeholder="incident or order id"
              className="num w-64 border border-[color:var(--border-strong)] px-2 py-1"
            />
          </label>
        </div>

        <Region state={state} rows={10}>
          {(data) =>
            data.entries.length === 0 ? (
              <Empty>No entries match this filter.</Empty>
            ) : (
              <>
                <Table columns={LEDGER_COLUMNS} minWidth="68rem">
                  {data.entries.map((entry) => (
                    <tr key={entry.seq} className="align-top">
                      <Cell column="seq">{entry.seq}</Cell>
                      <Cell column="time">
                        <span className="dt-mono whitespace-nowrap">{timestamp(entry.ts)}</span>
                      </Cell>
                      <Cell column="kind">
                        <span className="dt-mono text-[color:var(--text-primary)]">{entry.kind}</span>
                      </Cell>
                      <Cell column="ref">
                        <span className="dt-mono">{entry.ref_type}</span>
                        <div className="dt-mono text-[color:var(--text-muted)]">{entry.ref_id}</div>
                      </Cell>
                      <Cell column="summary">
                        <span className="text-[length:var(--fs-meta)]">{summarise(entry)}</span>
                        <Disclosure summary="payload" className="mt-2">
                          <Code>{JSON.stringify(entry.payload, null, 2)}</Code>
                          <div className="dt-mono mt-2 text-[length:var(--fs-micro)] text-[color:var(--text-muted)]">
                            previous {shortHash(entry.prev_hash)}
                          </div>
                        </Disclosure>
                      </Cell>
                      <Cell column="hash">
                        <span className="dt-mono">{shortHash(entry.hash)}</span>
                      </Cell>
                    </tr>
                  ))}
                </Table>
                <div className="mt-3 flex items-center gap-3 text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">
                  <span className="num">{data.total} entries</span>
                  <button
                    type="button"
                    disabled={cursor === 0}
                    onClick={() => setCursor(0)}
                    className="btn btn-sm focus-ring"
                  >
                    First page
                  </button>
                  <button
                    type="button"
                    disabled={data.next_cursor === null}
                    onClick={() => setCursor(data.next_cursor ?? cursor)}
                    className="btn btn-sm focus-ring"
                  >
                    Next 50
                  </button>
                </div>
              </>
            )
          }
        </Region>
      </Panel>
    </div>
  );
}
