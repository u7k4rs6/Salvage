import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useApi } from "../lib/useApi";
import { FULL_CONSOLE } from "../lib/build";
import { Badge, Empty, Panel, Region, Table } from "../components/primitives";
import { count, percent, rupees, rupeesShort } from "../lib/format";
import type { ResultsRun } from "../lib/types";

interface RunList {
  runs: { run_id: string; scenarios: string[]; seeds: number[]; policies: string[]; runs: number }[];
  latest: string | null;
  notes: string[];
}

function Notes({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null;
  return (
    <div className="border border-[color:var(--warn)] bg-[color:var(--warn-bg)] px-3 py-2 text-xs text-[color:var(--warn)]">
      {notes.map((note, index) => (
        <p key={index} className={index > 0 ? "mt-1" : ""}>
          {note}
        </p>
      ))}
    </div>
  );
}

function AtRiskTable({ run }: { run: ResultsRun }) {
  const scenarios = run.scenarios;
  const policies = run.policies;
  const find = (scenario: string, policy: string) =>
    run.aggregates.find((row) => row.scenario === scenario && row.policy === policy);

  return (
    <Table columns={["scenario", "at-risk orders", ...policies]}>
      {scenarios.map((scenario) => {
        const atRisk = find(scenario, policies[0])?.at_risk_orders ?? 0;
        return (
          <tr key={scenario} className="border-b border-[color:var(--line)]">
            <td className="cell-pad num font-medium">{scenario}</td>
            <td className="cell-pad num text-right">{count(atRisk, 0)}</td>
            {policies.map((policy) => {
              const row = find(scenario, policy);
              if (!row) return <td key={policy} className="cell-pad text-[color:var(--fg-3)]">not run</td>;
              return (
                <td key={policy} className="cell-pad num text-right">
                  <div className="font-medium">{rupees(row.at_risk_recovered_amount)}</div>
                  <div className="text-[11px] text-[color:var(--fg-2)]">
                    {count(row.at_risk_messages, 0)} msg
                  </div>
                  <div className="text-[11px] text-[color:var(--fg-3)]">
                    rate {percent(row.at_risk_recovery_rate, 1)}
                  </div>
                </td>
              );
            })}
          </tr>
        );
      })}
    </Table>
  );
}

function WholeRunTable({ run }: { run: ResultsRun }) {
  const find = (scenario: string, policy: string) =>
    run.aggregates.find((row) => row.scenario === scenario && row.policy === policy);
  return (
    <Table columns={["scenario", ...run.policies]}>
      {run.scenarios.map((scenario) => (
        <tr key={scenario} className="border-b border-[color:var(--line)]">
          <td className="cell-pad num font-medium">{scenario}</td>
          {run.policies.map((policy) => {
            const row = find(scenario, policy);
            if (!row) return <td key={policy} className="cell-pad text-[color:var(--fg-3)]">not run</td>;
            return (
              <td key={policy} className="cell-pad num text-right">
                <div>{rupees(row.recovered_amount)}</div>
                <div className="text-[11px] text-[color:var(--fg-3)]">
                  sd {rupeesShort(row.recovered_std)} / {count(row.messages, 0)} msg /{" "}
                  {count(row.opt_outs, 0)} opt-out
                </div>
              </td>
            );
          })}
        </tr>
      ))}
    </Table>
  );
}

function SecondaryTable({ run }: { run: ResultsRun }) {
  return (
    <Table
      columns={[
        "scenario",
        "policy",
        "recovery rate",
        "contacts per 1000 rupees",
        "time to detect",
        "escalations",
        "violations",
      ]}
      align={["left", "left", "right", "right", "right", "right", "right"]}
    >
      {run.aggregates.map((row) => (
        <tr key={`${row.scenario}-${row.policy}`} className="border-b border-[color:var(--line)]">
          <td className="cell-pad num">{row.scenario}</td>
          <td className="cell-pad num">{row.policy}</td>
          <td className="cell-pad num text-right">{percent(row.recovery_rate)}</td>
          <td className="cell-pad num text-right">{count(row.contacts_per_1000, 2)}</td>
          <td className="cell-pad num text-right">
            {row.time_to_detect === null ? "not detected" : `${count(row.time_to_detect, 1)} min`}
          </td>
          <td className="cell-pad num text-right">{count(row.escalations, 1)}</td>
          <td className="cell-pad num text-right">
            {row.violations === 0 ? (
              <span className="text-[color:var(--ok)]">0</span>
            ) : (
              <span className="text-[color:var(--crit)]">{row.violations}</span>
            )}
          </td>
        </tr>
      ))}
    </Table>
  );
}

/**
 * Where these figures came from, said on the page rather than left to be inferred.
 *
 * In the console this page reads a live API against whatever `data/results` holds right now. In the
 * public demo there is no API, and the same routes are answered from a capture committed to the
 * repository. The numbers are identical either way, but "identical" is a thing a reader has to be
 * told rather than something they can see, and a table of revenue figures with no date on it reads
 * as current by default. So the demo says plainly that it is a snapshot, and names the run it is a
 * snapshot of, which is the same run id the tables below are keyed on.
 */
function CaptureNotice({ runId }: { runId: string | null }) {
  if (FULL_CONSOLE) return null;
  return (
    <p className="mb-3 border-l-2 border-[color:var(--line-2)] pl-3 text-xs text-[color:var(--fg-2)]">
      These figures are a captured snapshot of a real evaluation run
      {runId ? (
        <>
          {" "}
          (<span className="num">{runId}</span>)
        </>
      ) : null}
      , not a live readout. They are the unedited output of the same API route the console reads,
      recorded once from <span className="num">data/results/</span> and committed to the repository.
      Nothing on this page is computed in the browser.
    </p>
  );
}

export default function ResultsPage() {
  const runs = useApi<RunList>("/api/results");
  const [selected, setSelected] = useState<string | null>(null);
  const runId = selected ?? runs.data?.latest ?? null;
  const run = useApi<ResultsRun>(runId ? `/api/results/${runId}` : null, [runId]);

  return (
    <div className="space-y-4">
      <Region state={runs} rows={2}>
        {(list) =>
          list.runs.length === 0 ? (
            <Panel title="Results">
              <Empty>
                No evaluation runs yet. Run{" "}
                <code className="num">
                  salvage eval run --scenarios S0,S1,S2,S3,S4 --seeds 0..9
                </code>
                .
              </Empty>
            </Panel>
          ) : (
            <Panel
              title="Results"
              right={
                <label className="text-xs text-[color:var(--fg-2)]">
                  run{" "}
                  <select
                    value={runId ?? ""}
                    onChange={(event) => setSelected(event.target.value)}
                    className="num border border-[color:var(--line-2)] px-2 py-1 text-xs"
                  >
                    {list.runs.map((item) => (
                      <option key={item.run_id} value={item.run_id}>
                        {item.run_id} ({item.runs} runs)
                      </option>
                    ))}
                  </select>
                </label>
              }
            >
              <CaptureNotice runId={runId} />
              <Notes notes={list.notes} />
            </Panel>
          )
        }
      </Region>

      <Region state={run} rows={8}>
        {(data) => (
          <div className="space-y-4">
            {data.notes.length > 0 && <Notes notes={data.notes} />}

            <Panel
              title="Primary: recovered revenue over the at-risk order set"
              subtitle="An order is at risk when its first attempt failed inside a fault window and on the instrument that fault was breaking. Identical across arms by construction. Revenue is never shown without contact volume beside it. Opt-outs are whole-run and sit in the table below, because a policy sends inside and outside this set alike."
            >
              {data.at_risk_measured ? (
                <AtRiskTable run={data} />
              ) : (
                <Empty>
                  This run predates the at-risk order set, so those columns are not measured. They
                  are left blank rather than shown as zeros.
                </Empty>
              )}
            </Panel>

            <Panel
              title="Secondary: whole-run totals"
              subtitle="Every order whose first attempt failed during the evaluation day, fault or not. S0 has no fault at all, and a link-sending baseline still scores well there: that is ordinary background failure, not recovery."
            >
              <WholeRunTable run={data} />
            </Panel>

            <Panel title="Secondary metrics">
              <SecondaryTable run={data} />
              <div className="mt-3 flex flex-wrap gap-3 text-xs">
                <span>
                  worlds{" "}
                  <span className="num">
                    {data.worlds}
                  </span>
                </span>
                <Badge tone={data.worlds_identical ? "green" : "red"}>
                  {data.worlds_identical
                    ? "every policy faced an identical world"
                    : "worlds differ between policies"}
                </Badge>
                <Badge tone={data.violations === 0 ? "green" : "red"}>
                  {data.violations} policy violations
                </Badge>
              </div>
            </Panel>

            {data.diagnosis && (
              <Panel
                title="Diagnosis ablation"
                subtitle={String(data.diagnosis.provenance ?? "")}
              >
                <Table columns={["scenario", "incidents", "rules accuracy", "LLM accuracy"]}>
                  {(data.diagnosis.rows ?? []).map((row: any) => (
                    <tr key={row.scenario} className="border-b border-[color:var(--line)]">
                      <td className="cell-pad num">{row.scenario}</td>
                      <td className="cell-pad num text-right">{row.incidents}</td>
                      <td className="cell-pad num text-right">{percent(row.rules_accuracy)}</td>
                      <td className="cell-pad num text-right text-[color:var(--fg-3)]">
                        {typeof row.llm_accuracy === "number"
                          ? percent(row.llm_accuracy)
                          : "unmeasured"}
                      </td>
                    </tr>
                  ))}
                </Table>
                {(data.diagnosis.misses ?? []).length > 0 && (
                  <ul className="mt-2 space-y-0.5">
                    {data.diagnosis.misses.map((miss: string, index: number) => (
                      <li key={index} className="num text-[11px] text-[color:var(--fg-2)]">
                        {miss}
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            )}

            {data.sensitivity && (
              <Panel
                title="Sensitivity"
                subtitle="Recovered revenue for the link-sending baseline minus the do-nothing baseline as the response multipliers scale. The result survives the response model being wrong by a factor of two in either direction."
              >
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data.sensitivity.rows ?? []}>
                      <CartesianGrid stroke="#22262c" vertical={false} />
                      <XAxis dataKey="scale" tick={{ fontSize: 11 }} stroke="#69727d" />
                      <YAxis
                        tick={{ fontSize: 11 }}
                        stroke="#69727d"
                        width={70}
                        tickFormatter={(value) => rupeesShort(Number(value))}
                      />
                      <Tooltip
                        formatter={(value) => rupees(Number(value))}
                        contentStyle={{ fontSize: 12 }}
                      />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      <Line
                        type="monotone"
                        dataKey="delta"
                        stroke="#58a6ff"
                        name="B1 minus B0"
                        dot
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                {data.sensitivity.adversarial && (
                  <div className="mt-3">
                    <h3 className="text-xs font-medium uppercase tracking-wide text-[color:var(--fg-2)]">
                      Adversarial set
                    </h3>
                    <p className="mt-1 text-xs text-[color:var(--fg-2)]">
                      Organic retry probability raised to 0.60 everywhere and every response
                      multiplier set to 1.0. Customers recover on their own; the agent has no
                      advantage here, by design.
                    </p>
                    <Table
                      columns={[
                        "scenario",
                        ...(data.sensitivity.adversarial.policies ?? []),
                      ]}
                    >
                      {(data.sensitivity.adversarial.rows ?? []).map((row: any) => (
                        <tr key={row.scenario} className="border-b border-[color:var(--line)]">
                          <td className="cell-pad num">{row.scenario}</td>
                          {(data.sensitivity.adversarial.policies ?? []).map((policy: string) => (
                            <td key={policy} className="cell-pad num text-right">
                              {rupees(row.by_policy[policy])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </Table>
                  </div>
                )}
              </Panel>
            )}

            {data.fault_injection && (
              <Panel
                title="Fault injection"
                subtitle="Every injected fault, and whether the agent refused it and wrote the refusal down."
              >
                <div className="grid grid-cols-2 gap-3 text-xs lg:grid-cols-4">
                  <div>
                    <div className="text-[color:var(--fg-2)]">attempts</div>
                    <div className="num text-lg">{data.fault_injection.attempts}</div>
                  </div>
                  <div>
                    <div className="text-[color:var(--fg-2)]">refused</div>
                    <div className="num text-lg text-[color:var(--ok)]">
                      {data.fault_injection.refused}
                    </div>
                  </div>
                  <div>
                    <div className="text-[color:var(--fg-2)]">ledgered</div>
                    <div className="num text-lg">{data.fault_injection.ledgered}</div>
                  </div>
                  <div>
                    <div className="text-[color:var(--fg-2)]">unrefused</div>
                    <div
                      className={`num text-lg ${
                        (data.fault_injection.unrefused ?? []).length === 0
                          ? "text-[color:var(--ok)]"
                          : "text-[color:var(--crit)]"
                      }`}
                    >
                      {(data.fault_injection.unrefused ?? []).length}
                    </div>
                  </div>
                </div>
              </Panel>
            )}
          </div>
        )}
      </Region>
    </div>
  );
}
