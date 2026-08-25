import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { useStream, type StreamEvent } from "../lib/useStream";
import { post } from "../lib/api";
import { Badge, Empty, ErrorPanel, Panel, Region, Stat } from "../components/primitives";
import { count, rupees, timeOnly } from "../lib/format";
import type { SimStatus } from "../lib/types";

const SCENARIOS = [
  { value: "S0", label: "S0 control, no fault" },
  { value: "S1", label: "S1 UPI handle outage" },
  { value: "S2", label: "S2 card BIN authorisation failures" },
  { value: "S3", label: "S3 gateway degradation" },
  { value: "S4", label: "S4 merchant misconfiguration" },
  { value: "S5", label: "S5 customer-side noise" },
];

const POLICIES = ["agent", "B0", "B1", "B2"];

export default function ScenarioRunnerPage() {
  const { token } = useSession();
  const status = useApi<SimStatus>("/api/sim/status");
  const [scenario, setScenario] = useState("S1");
  const [seed, setSeed] = useState(1);
  const [policy, setPolicy] = useState("agent");
  const [variant, setVariant] = useState("peak");
  const [log, setLog] = useState<StreamEvent[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [incidentIds, setIncidentIds] = useState<string[]>([]);

  useStream(
    [
      "sim.tick",
      "sim.finished",
      "incident.opened",
      "action.executed",
      "action.refused",
      "escalation.opened",
    ],
    (event) => {
      setLog((current) => [event, ...current].slice(0, 50));
      if (event.name === "incident.opened" && typeof event.data.id === "string") {
        setIncidentIds((current) => Array.from(new Set([...current, event.data.id as string])));
      }
      if (event.name === "sim.finished") status.reload();
    },
  );

  // While a run is active the status is the only thing that tells the form to stay disabled, and
  // the run holds the request open, so a poll is the honest way to know it ended.
  useEffect(() => {
    if (!status.data?.running) return;
    const timer = window.setInterval(() => status.reload(), 2000);
    return () => window.clearInterval(timer);
  }, [status.data?.running, status]);

  const running = status.data?.running ?? false;
  const summary = status.data?.summary ?? {};

  async function run() {
    setBusy(true);
    setError(null);
    setIncidentIds([]);
    try {
      await post("/api/sim/run", { scenario, seed, policy, variant }, token);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
      status.reload();
    }
  }

  return (
    <div className="space-y-4">
      <Panel
        title="Scenario Runner"
        subtitle="Runs the simulator, the detector and one policy against a fresh world, then measures it. One run at a time."
      >
        <div className="flex flex-wrap items-end gap-4 text-xs">
          <label className="flex flex-col gap-1">
            scenario
            <select
              value={scenario}
              onChange={(event) => setScenario(event.target.value)}
              disabled={running}
              className="w-64 border border-neutral-300 px-2 py-1 disabled:bg-neutral-100"
            >
              {SCENARIOS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            seed
            <input
              type="number"
              min={0}
              max={999}
              value={seed}
              onChange={(event) => setSeed(Number(event.target.value))}
              disabled={running}
              className="num w-20 border border-neutral-300 px-2 py-1 disabled:bg-neutral-100"
            />
          </label>
          <label className="flex flex-col gap-1">
            policy
            <select
              value={policy}
              onChange={(event) => setPolicy(event.target.value)}
              disabled={running}
              className="border border-neutral-300 px-2 py-1 disabled:bg-neutral-100"
            >
              {POLICIES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            traffic
            <select
              value={variant}
              onChange={(event) => setVariant(event.target.value)}
              disabled={running}
              className="border border-neutral-300 px-2 py-1 disabled:bg-neutral-100"
            >
              <option value="peak">peak</option>
              <option value="offpeak">off-peak</option>
            </select>
          </label>

          <button
            type="button"
            onClick={run}
            disabled={running || busy || !token}
            title={token ? undefined : "enter the token"}
            className="border border-accent bg-accent-soft px-3 py-1 text-accent-hover hover:bg-teal-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {!token && <span aria-hidden="true">&#128274; </span>}
            {busy || running ? "Running" : "Run"}
          </button>
          <button
            type="button"
            onClick={async () => {
              try {
                await post("/api/sim/stop", {}, token);
              } catch (cause) {
                setError(cause);
              } finally {
                status.reload();
              }
            }}
            disabled={!running || !token}
            className="border border-red-400 bg-red-50 px-3 py-1 text-red-800 hover:bg-red-100 disabled:opacity-50"
          >
            Stop
          </button>
        </div>

        {running && (
          <p className="mt-3 text-xs text-amber-800">
            A run is active ({status.data?.scenario} seed {status.data?.seed}, policy{" "}
            {status.data?.policy}). The form is disabled until it finishes: a second run against
            the same database would interleave two worlds.
          </p>
        )}
        {status.data?.stop_requested && running && (
          <p className="mt-1 text-xs text-neutral-700">
            Stop requested. The current run finishes rather than being cut off mid-write. To stop
            outbound actions immediately, use the kill switch in the top bar.
          </p>
        )}
        {!token && (
          <p className="mt-3 text-xs text-neutral-600">
            Running a scenario is a mutating action. Enter the dashboard token in the top bar.
          </p>
        )}
        {error !== null && (
          <div className="mt-3">
            <ErrorPanel error={error} />
          </div>
        )}
        {status.data?.error && !error && (
          <p className="mt-3 text-xs text-red-700">Last run failed: {status.data.error}</p>
        )}
      </Panel>

      <Region state={status} rows={2}>
        {(data) =>
          Object.keys(data.summary).length === 0 ? (
            <Panel title="Last run">
              <Empty>No run yet in this process.</Empty>
            </Panel>
          ) : (
            <Panel
              title="Last run"
              subtitle={`${data.summary.scenario} seed ${data.summary.seed}, policy ${data.summary.policy}, ${data.summary.variant} traffic, model ${data.summary.provider}`}
            >
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Stat label="Attempts" value={count(Number(summary.attempts))} />
                <Stat label="Incidents" value={count(Number(summary.incidents))} />
                <Stat
                  label="Actions executed"
                  value={count(Number(summary.actions_executed))}
                  hint={`${count(Number(summary.actions_refused))} refused`}
                />
                <Stat
                  label="Messages"
                  value={count(Number(summary.messages_sent))}
                  hint={`${count(Number(summary.opt_outs))} opt-outs`}
                />
                <Stat
                  label="At-risk orders"
                  value={count(Number(summary.at_risk_orders))}
                  hint="failed inside a fault window on the broken instrument"
                />
                <Stat
                  label="At-risk recovered"
                  value={rupees(Number(summary.at_risk_recovered_amount))}
                  tone="green"
                  hint={`${count(Number(summary.at_risk_recovered_orders))} orders`}
                />
                <Stat label="Escalations" value={count(Number(summary.escalations))} />
                <Stat
                  label="Policy violations"
                  value={count(Number(summary.policy_violations))}
                  tone={Number(summary.policy_violations) > 0 ? "red" : "green"}
                />
              </div>
              {incidentIds.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {incidentIds.map((id) => (
                    <Link
                      key={id}
                      to={`/incidents/${id}`}
                      className="num border border-neutral-300 px-2 py-1 text-xs text-accent hover:bg-neutral-50"
                    >
                      {id}
                    </Link>
                  ))}
                </div>
              )}
            </Panel>
          )
        }
      </Region>

      <Panel title="Live log" subtitle="The last 50 stream events, newest first.">
        {log.length === 0 ? (
          <Empty>Nothing on the stream yet.</Empty>
        ) : (
          <ul className="max-h-80 space-y-0.5 overflow-y-auto">
            {log.map((event, index) => (
              <li key={`${event.at}-${index}`} className="num flex gap-2 text-[11px]">
                <span className="w-16 shrink-0 text-neutral-500">
                  {timeOnly(Math.floor(event.at / 1000))}
                </span>
                <Badge>{event.name}</Badge>
                <span className="truncate text-neutral-700">{JSON.stringify(event.data)}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
