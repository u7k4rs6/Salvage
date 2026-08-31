import { useState, type ReactNode } from "react";
import { post, describe } from "../lib/api";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { useStream, useStreamState } from "../lib/useStream";
import { Badge, ConfirmButton } from "./primitives";
import { FULL_CONSOLE } from "../lib/build";
import type { Health, Overview } from "../lib/types";

/**
 * Environment, clock, active incident count, model, kill switch and token entry (spec section 2).
 *
 * A strip of readouts in three groups rather than a row of pills: identity, then the world the
 * console is looking at, then that world's current state. The grouping is done with hairline
 * separators and with type weight, because ten bordered chips in a row read as ten equally
 * important things and none of them is.
 *
 * The kill switch is the one control visible from every page, because the point of it is that a
 * human can stop the agent without having to find the right screen first.
 */

/** One label-and-value pair. The class names are hooks the Overview's dark chrome overrides. */
function Readout({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="readout">
      <span className="readout-label">{label}</span>
      <span className="readout-value">{children}</span>
    </span>
  );
}


/**
 * The bar picks which of the two below to render, and it has to be a fork between components
 * rather than a branch inside one, because the live bar opens an event stream and polls three
 * routes from hooks that cannot be called conditionally.
 */
export function TopBar() {
  return FULL_CONSOLE ? <LiveBar /> : <DemoBar />;
}

/**
 * The public demo's bar: what this is, and that it is a recording.
 *
 * No clock, no incident count, no model, no stream, no token field and no kill switch. Every one
 * of those reads a backend that a static deployment does not have, and a row of readouts showing
 * "..." next to a red "disconnected" is a worse first impression than no row at all. The kill
 * switch in particular is a control over a running agent; there is no agent running here.
 */
/**
 * The public demo's bar. No clock, no incident count, no stream, no token and no kill switch:
 * every one of those reads a backend that a static deployment does not have, and a row of
 * readouts showing "..." beside a red "disconnected" is a worse first impression than no row.
 */
function DemoBar() {
  return (
    <header className="statusbar">
      <span className="text-[length:var(--fs-body)] font-semibold tracking-[var(--ls-tight)] text-[color:var(--text-primary)]">
        Salvage
      </span>
      <span className="statusbar-sep" aria-hidden="true" />
      <span className="text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">
        Payment failure recovery for Indian merchants on Razorpay
      </span>
      <span className="ml-auto text-[length:var(--fs-meta)] text-[color:var(--text-muted)]">
        A recorded run, replayed. Nothing here is live.
      </span>
    </header>
  );
}

function LiveBar() {
  const { token, setToken } = useSession();
  const health = useApi<Health>("/api/health");
  const overview = useApi<Overview>("/api/overview");
  const stream = useStreamState();
  const [error, setError] = useState<unknown>(null);

  useStream(["incident.opened", "incident.closed", "sim.finished"], () => overview.reload());

  const killed = health.data?.kill_switch ?? false;
  const open = (overview.data?.incidents ?? []).filter((i) => !i.id.endsWith("_baseline")).length;
  const env = health.data?.env ?? "...";
  const clockLabel = overview.data?.clock === "sim" ? "sim clock" : "wall clock";

  return (
    <header className="statusbar">
      {/* Identity */}
      <span className="flex items-baseline gap-2">
        <span className="text-[length:var(--fs-body)] font-semibold tracking-[var(--ls-tight)] text-[color:var(--text-primary)]">
          Salvage
        </span>
        <span className="text-[length:var(--fs-micro)] text-[color:var(--text-muted)]">{env}</span>
      </span>

      <span className="statusbar-sep" aria-hidden="true" />

      {/* The world this console is looking at */}
      <Readout label={clockLabel}>
        {overview.data
          ? new Date(overview.data.now * 1000).toLocaleString("en-IN", {
              timeZone: "Asia/Kolkata",
              hour12: false,
            })
          : "not loaded"}
      </Readout>
      <span className="readout">
        <span className="readout-label">stream</span>
        <Badge tone={stream === "disconnected" ? "danger" : "success"}>{stream}</Badge>
      </span>

      <span className="statusbar-sep" aria-hidden="true" />

      {/* That world's current state */}
      <span className="readout">
        <span className="readout-label">incidents</span>
        <Badge tone={open > 0 ? "danger" : "neutral"} dot={open > 0}>
          {String(open).padStart(2, "0")}
        </Badge>
      </span>
      <Readout label="model">{health.data?.llm_provider ?? "not loaded"}</Readout>

      {killed && (
        <>
          <span className="statusbar-sep" aria-hidden="true" />
          <Badge tone="danger">Outbound actions suspended</Badge>
        </>
      )}

      <div className="ml-auto flex items-center gap-3">
        <label className="readout">
          <span className="readout-label">token</span>
          <input
            type="password"
            value={token ?? ""}
            onChange={(event) => setToken(event.target.value || null)}
            placeholder="dashboard token"
            className="field w-44 font-[family-name:var(--font-mono)]"
          />
        </label>

        <ConfirmButton
          label={killed ? "Resume outbound actions" : "Suspend outbound actions"}
          confirmLabel={killed ? "Resume" : "Suspend"}
          tone={killed ? "success" : "danger"}
          prompt={
            killed
              ? "Resume outbound actions. Detection and diagnosis have been running the whole time."
              : "Suspend all outbound actions. Detection and diagnosis keep running; nothing is sent."
          }
          disabled={!token}
          disabledReason={token ? undefined : "enter the token"}
          onConfirm={async () => {
            setError(null);
            try {
              await post("/api/control/kill-switch", { enabled: !killed }, token);
              health.reload();
            } catch (cause) {
              setError(cause);
              throw cause;
            }
          }}
        />
      </div>

      {error !== null && (
        <div className="bar-crit w-full text-[length:var(--fs-meta)] text-[color:var(--danger)]" role="alert">
          {describe(error)}
        </div>
      )}
    </header>
  );
}
