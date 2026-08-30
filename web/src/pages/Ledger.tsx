import { useState } from "react";
import { useApi } from "../lib/useApi";
import { post } from "../lib/api";
import { useStream } from "../lib/useStream";
import {
  Badge,
  Code,
  Disclosure,
  Empty,
  ErrorPanel,
  Panel,
  Region,
  Table,
} from "../components/primitives";
import { summarise } from "../components/Timeline";
import { shortHash, timestamp } from "../lib/format";
import type { LedgerPage, VerifyResult } from "../lib/types";

const REF_TYPES = ["", "sim_run", "incident", "case", "action", "escalation", "webhook", "control"];

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
      <Panel
        title="Ledger"
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
              className="border border-[color:var(--info)] bg-[color:var(--info-bg)] px-2 py-1 text-xs text-[color:var(--info)] hover:bg-[color:var(--info-bg)]"
            >
              Verify chain
            </button>
            <a
              href="/api/ledger/export"
              download="salvage-ledger.jsonl"
              className="border border-[color:var(--line-2)] bg-[color:var(--panel)] px-2 py-1 text-xs hover:bg-[color:var(--panel-3)]"
            >
              Export JSONL
            </a>
          </div>
        }
      >
        <p className="max-w-3xl text-xs text-[color:var(--fg-2)]">
          {state.data?.proves ??
            "This chain proves the record has not been altered after it was written. It does not prove the process wrote the truth."}
        </p>

        {verifyError !== null && (
          <div className="mt-3">
            <ErrorPanel error={verifyError} />
          </div>
        )}

        {verify && (
          <div
            role="status"
            className={`mt-3 border px-3 py-2 text-sm ${
              verify.ok
                ? "border-[color:var(--ok)] bg-[color:var(--ok-bg)] text-[color:var(--ok)]"
                : "border-[color:var(--crit)] bg-[color:var(--crit-bg)] text-[color:var(--crit)]"
            }`}
          >
            {/* The server's message already opens with the verdict, so the banner shows it
                once rather than prefixing a second copy of the same word. */}
            <span className="num font-medium">{verify.message}</span>
            <div className="num mt-1 text-[11px] opacity-80">
              genesis {shortHash(verify.genesis_hash)}
            </div>
          </div>
        )}
      </Panel>

      <Panel title="Entries">
        <div className="mb-3 flex flex-wrap items-end gap-3 text-xs">
          <label className="flex flex-col gap-1">
            kind
            <select
              value={kind}
              onChange={(event) => {
                setKind(event.target.value);
                setCursor(0);
              }}
              className="border border-[color:var(--line-2)] px-2 py-1"
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
              className="border border-[color:var(--line-2)] px-2 py-1"
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
              className="num w-64 border border-[color:var(--line-2)] px-2 py-1"
            />
          </label>
        </div>

        <Region state={state} rows={10}>
          {(data) =>
            data.entries.length === 0 ? (
              <Empty>No entries match this filter.</Empty>
            ) : (
              <>
                <Table
                  columns={["seq", "time", "kind", "ref", "summary", "hash"]}
                  align={["right", "left", "left", "left", "left", "left"]}
                >
                  {data.entries.map((entry) => (
                    <tr key={entry.seq} className="border-b border-[color:var(--line)] align-top">
                      <td className="cell-pad num text-right text-xs">{entry.seq}</td>
                      <td className="cell-pad num whitespace-nowrap text-xs">
                        {timestamp(entry.ts)}
                      </td>
                      <td className="cell-pad">
                        <Badge>{entry.kind}</Badge>
                      </td>
                      <td className="cell-pad num text-xs text-[color:var(--fg-2)]">
                        {entry.ref_type}
                        <div className="text-[color:var(--fg-3)]">{entry.ref_id}</div>
                      </td>
                      <td className="cell-pad text-xs">
                        {summarise(entry)}
                        <Disclosure summary="payload" className="mt-1">
                          <Code>{JSON.stringify(entry.payload, null, 2)}</Code>
                          <div className="num mt-1 text-[11px] text-[color:var(--fg-3)]">
                            previous {shortHash(entry.prev_hash)}
                          </div>
                        </Disclosure>
                      </td>
                      <td className="cell-pad num text-xs text-[color:var(--fg-2)]">
                        {shortHash(entry.hash)}
                      </td>
                    </tr>
                  ))}
                </Table>
                <div className="mt-3 flex items-center gap-3 text-xs text-[color:var(--fg-2)]">
                  <span className="num">{data.total} entries</span>
                  <button
                    type="button"
                    disabled={cursor === 0}
                    onClick={() => setCursor(0)}
                    className="border border-[color:var(--line-2)] px-2 py-1 disabled:opacity-40"
                  >
                    First page
                  </button>
                  <button
                    type="button"
                    disabled={data.next_cursor === null}
                    onClick={() => setCursor(data.next_cursor ?? cursor)}
                    className="border border-[color:var(--line-2)] px-2 py-1 disabled:opacity-40"
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
