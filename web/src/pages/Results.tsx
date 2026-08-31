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
import {
  Badge,
  Cell,
  Empty,
  Metric,
  Panel,
  Region,
  Table,
  type Column,
} from "../components/primitives";
import { count, percent, rupees, rupeesShort } from "../lib/format";
import type { ResultsRun } from "../lib/types";
import { PageIntro } from "../components/PageIntro";

interface RunList {
  runs: { run_id: string; scenarios: string[]; seeds: number[]; policies: string[]; runs: number }[];
  latest: string | null;
  notes: string[];
}

function Notes({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null;
  return (
    <div className="border border-[color:var(--warning)] bg-[color:var(--warning-bg)] px-3 py-2 text-[length:var(--fs-meta)] text-[color:var(--warning)]">
      {notes.map((note, index) => (
        <p
          key={index}
          className={` leading-[var(--lh-normal)] ${index > 0 ? "mt-2" : ""}`}
        >
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

  // Every policy column is numeric, so the recovered figure, the action count and the rate all
  // share one right edge down the whole table, whatever their digit lengths.
  const columns: Column[] = [
    // The two identifying columns are narrow because their content is: a scenario id and a count
    // of at most four digits. The five arms are the comparison, so they take the rest in equal
    // shares and every boundary between them falls at the same interval.
    { key: "scenario", label: "Scenario", align: "text", flex: 0.9 },
    { key: "at_risk", label: "At-risk orders", align: "num", flex: 1.3 },
    ...policies.map((policy) => ({ key: policy, label: policy, align: "num" as const, flex: 1.56 })),
  ];

  return (
    <Table columns={columns} minWidth="62rem">
      {scenarios.map((scenario) => {
        const atRisk = find(scenario, policies[0])?.at_risk_orders ?? 0;
        return (
          <tr key={scenario}>
            <Cell column="scenario">
              <span className="font-medium text-[color:var(--text-primary)]">{scenario}</span>
            </Cell>
            <Cell column="at_risk">{count(atRisk, 0)}</Cell>
            {policies.map((policy) => {
              const row = find(scenario, policy);
              return (
                <Cell key={policy} column={policy}>
                  {row ? (
                    <Metric
                      value={rupees(row.at_risk_recovered_amount)}
                      secondary={[
                        `${count(row.at_risk_messages, 0)} actions`,
                        `rate ${percent(row.at_risk_recovery_rate, 1)}`,
                      ]}
                    />
                  ) : (
                    <span className="text-[color:var(--text-muted)]">not run</span>
                  )}
                </Cell>
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
  const columns: Column[] = [
    { key: "scenario", label: "Scenario", align: "text", flex: 1 },
    ...run.policies.map((policy) => ({ key: policy, label: policy, align: "num" as const, flex: 1.8 })),
  ];
  return (
    <Table columns={columns} minWidth="80rem">
      {run.scenarios.map((scenario) => (
        <tr key={scenario}>
          <Cell column="scenario">
            <span className="font-medium text-[color:var(--text-primary)]">{scenario}</span>
          </Cell>
          {run.policies.map((policy) => {
            const row = find(scenario, policy);
            return (
              <Cell key={policy} column={policy}>
                {row ? (
                  <Metric
                    value={rupees(row.recovered_amount)}
                    secondary={[
                      `sd ${rupeesShort(row.recovered_std)}`,
                      `${count(row.messages, 0)} actions · ${count(row.opt_outs, 0)} opt-out`,
                    ]}
                  />
                ) : (
                  <span className="text-[color:var(--text-muted)]">not run</span>
                )}
              </Cell>
            );
          })}
        </tr>
      ))}
    </Table>
  );
}

function SecondaryTable({ run }: { run: ResultsRun }) {
  const columns: Column[] = [
    { key: "scenario", label: "Scenario", align: "text", flex: 1 },
    { key: "policy", label: "Policy", align: "text", flex: 1 },
    { key: "rate", label: "Recovery rate", align: "num", flex: 1.6 },
    { key: "contacts", label: "Actions per 1,000 rupees", align: "num", flex: 2 },
    { key: "detect", label: "Time to detect", align: "num", flex: 1.6 },
    { key: "escalations", label: "Escalations", align: "num", flex: 1.4 },
    { key: "violations", label: "Violations", align: "num", flex: 1.4 },
  ];
  return (
    <Table columns={columns} minWidth="62rem">
      {run.aggregates.map((row) => (
        <tr key={`${row.scenario}-${row.policy}`}>
          <Cell column="scenario">{row.scenario}</Cell>
          <Cell column="policy">{row.policy}</Cell>
          <Cell column="rate">{percent(row.recovery_rate)}</Cell>
          <Cell column="contacts">{count(row.contacts_per_1000, 2)}</Cell>
          <Cell column="detect">
            {row.time_to_detect === null ? (
              <span className="text-[color:var(--text-muted)]">not detected</span>
            ) : (
              `${count(row.time_to_detect, 1)} min`
            )}
          </Cell>
          <Cell column="escalations">{count(row.escalations, 1)}</Cell>
          <Cell column="violations">
            {row.violations > 0 ? (
              <span className="text-[color:var(--danger)]">{count(row.violations, 0)}</span>
            ) : (
              count(row.violations, 0)
            )}
          </Cell>
        </tr>
      ))}
    </Table>
  );
}

/**
 * Where these figures came from, said on the page rather than left to be inferred.
 *
 * In the console this page reads a live API. In the public demo there is no API and the same
 * routes are answered from a capture committed to the repository. The numbers are identical, but
 * "identical" is something a reader has to be told, and a table of revenue with no date on it
 * reads as current by default.
 */
function CaptureNotice({ runId }: { runId: string | null }) {
  if (FULL_CONSOLE) return null;
  return (
    <p className="mb-4 border-l-2 border-[color:var(--border-strong)] pl-3 text-[length:var(--fs-meta)] leading-[var(--lh-normal)] text-[color:var(--text-secondary)]">
      These figures are a captured snapshot of a real evaluation run
      {runId ? (
        <>
          {" "}
          (<span className="dt-mono">{runId}</span>)
        </>
      ) : null}
      , not a live readout. They are the unedited output of the same API route the console reads,
      recorded once from <span className="dt-mono">data/results/</span> and committed to the
      repository. Nothing on this page is computed in the browser.
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
      <PageIntro
        title="Results"
        what="How the agent scored against three simpler strategies over the same simulated worlds, ten seeds each."
        use="Read the primary table first, then the secondary one directly under it. They measure different populations and they disagree, and both are here on purpose."
        shows={[
          ["agent", "the full system: detect, diagnose, decide, act inside its rules"],
          ["echo", "the same agent with the language model replaced by a stub that repeats the rules verdict. A control, not a product"],
          ["B0", "does nothing. Whatever it recovers, the shoppers recovered on their own"],
          ["B1 and B2", "send a payment link to every failed order on fixed timers, with no idea why anything failed"],
          ["Primary table", "money recovered from the orders the fault actually broke, with the number of actions sent beside it. Revenue is never shown without contact volume"],
          ["Secondary table", "the same over every order that failed that day, fault or not. The link-sending baselines beat the agent here, on every scenario"],
        ]}
        caveat="A message costs nothing in this simulator except a 2.6 percent chance the shopper opts out. There is no regulatory cost, no per-message fee and no fatigue, so read every advantage a link-sending baseline shows in that light."
      />
      <Region state={runs} rows={2}>
        {(list) =>
          list.runs.length === 0 ? (
            <Panel>
              <Empty>
                No evaluation runs yet. Run{" "}
                <code className="dt-mono">
                  salvage eval run --scenarios S0,S1,S2,S3,S4 --seeds 0..9
                </code>
                .
              </Empty>
            </Panel>
          ) : (
            /* The run selector belongs to the page, not to a panel of its own: a panel whose only
               body is a dropdown is an empty box with a control in its header. */
            <>
              <div className="-mt-2 mb-6 flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 text-[length:var(--fs-meta)] text-[color:var(--text-muted)]">
                  Run
                  <select
                    value={runId ?? ""}
                    onChange={(event) => setSelected(event.target.value)}
                    className="field font-[family-name:var(--font-mono)]"
                  >
                    {list.runs.map((item) => (
                      <option key={item.run_id} value={item.run_id}>
                        {item.run_id} ({item.runs} runs)
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <CaptureNotice runId={runId} />
              <Notes notes={list.notes} />
            </>
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
              <div className="mt-3 flex flex-wrap gap-3 text-[length:var(--fs-meta)]">
                <span>
                  worlds{" "}
                  <span className="num">
                    {data.worlds}
                  </span>
                </span>
                <Badge tone={data.worlds_identical ? "success" : "danger"}>
                  {data.worlds_identical
                    ? "every policy faced an identical world"
                    : "worlds differ between policies"}
                </Badge>
                <Badge tone={data.violations === 0 ? "success" : "danger"}>
                  {data.violations} policy violations
                </Badge>
              </div>
            </Panel>

            {data.diagnosis && (
              <Panel
                title="Diagnosis ablation"
                subtitle={String(data.diagnosis.provenance ?? "")}
              >
                <Table
                  columns={[
                    { key: "scenario", label: "Scenario", align: "text", flex: 1 },
                    { key: "incidents", label: "Incidents", align: "num", flex: 1 },
                    { key: "rules", label: "Rules accuracy", align: "num", flex: 1.4 },
                    { key: "llm", label: "Model accuracy", align: "num", flex: 1.4 },
                  ]}
                >
                  {(data.diagnosis.rows ?? []).map((row: any) => (
                    <tr key={row.scenario}>
                      <Cell column="scenario">{row.scenario}</Cell>
                      <Cell column="incidents">{row.incidents}</Cell>
                      <Cell column="rules">{percent(row.rules_accuracy)}</Cell>
                      <Cell column="llm" className="text-[color:var(--text-muted)]">
                        {typeof row.llm_accuracy === "number"
                          ? percent(row.llm_accuracy)
                          : "unmeasured"}
                      </Cell>
                    </tr>
                  ))}
                </Table>
                {(data.diagnosis.misses ?? []).length > 0 && (
                  <ul className="mt-2 space-y-0.5">
                    {data.diagnosis.misses.map((miss: string, index: number) => (
                      <li key={index} className="num text-[length:var(--fs-micro)] text-[color:var(--text-secondary)]">
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
                      <CartesianGrid stroke="var(--border)" vertical={false} />
                      <XAxis dataKey="scale" tick={{ fontSize: 12, fill: "var(--text-muted)" }} stroke="var(--text-muted)" />
                      <YAxis
                        tick={{ fontSize: 12, fill: "var(--text-muted)" }}
                        stroke="var(--text-muted)"
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
                        stroke="var(--accent)"
                        name="B1 minus B0"
                        dot
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                {data.sensitivity.adversarial && (
                  <div className="mt-3">
                    <h3 className="text-[length:var(--fs-meta)] font-medium uppercase tracking-wide text-[color:var(--text-secondary)]">
                      Adversarial set
                    </h3>
                    <p className="mt-1 text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">
                      Organic retry probability raised to 0.60 everywhere and every response
                      multiplier set to 1.0. Customers recover on their own; the agent has no
                      advantage here, by design.
                    </p>
                    <Table
                      columns={[
                        { key: "scenario", label: "Scenario", align: "text", width: "8rem" },
                        ...((data.sensitivity.adversarial.policies ?? []) as string[]).map(
                          (policy) => ({ key: policy, label: policy, align: "num" as const }),
                        ),
                      ]}
                    >
                      {(data.sensitivity.adversarial.rows ?? []).map((row: any) => (
                        <tr key={row.scenario}>
                          <Cell column="scenario">{row.scenario}</Cell>
                          {((data.sensitivity.adversarial.policies ?? []) as string[]).map(
                            (policy) => (
                              <Cell key={policy} column={policy}>
                                {rupees(row.by_policy[policy])}
                              </Cell>
                            ),
                          )}
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
                <div className="grid grid-cols-2 gap-3 text-[length:var(--fs-meta)] lg:grid-cols-4">
                  <div>
                    <div className="text-[color:var(--text-secondary)]">attempts</div>
                    <div className="num text-[length:var(--fs-section)]">{data.fault_injection.attempts}</div>
                  </div>
                  <div>
                    <div className="text-[color:var(--text-secondary)]">refused</div>
                    <div className="num text-[length:var(--fs-section)] text-[color:var(--success)]">
                      {data.fault_injection.refused}
                    </div>
                  </div>
                  <div>
                    <div className="text-[color:var(--text-secondary)]">ledgered</div>
                    <div className="num text-[length:var(--fs-section)]">{data.fault_injection.ledgered}</div>
                  </div>
                  <div>
                    <div className="text-[color:var(--text-secondary)]">unrefused</div>
                    <div
                      className={`num text-[length:var(--fs-section)] ${
                        (data.fault_injection.unrefused ?? []).length === 0
                          ? "text-[color:var(--success)]"
                          : "text-[color:var(--danger)]"
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
