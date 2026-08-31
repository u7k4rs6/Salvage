import { useState, type ReactNode } from "react";
import { post, describe } from "../lib/api";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { useStream, useStreamState } from "../lib/useStream";
import { ConfirmButton } from "./primitives";
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
function Readout({
  label,
  tone = "ink",
  children,
}: {
  label: string;
  tone?: "ink" | "crit" | "warn" | "ok";
  children: ReactNode;
}) {
  const light =
    tone === "crit"
      ? "text-[color:var(--crit)]"
      : tone === "warn"
        ? "text-[color:var(--warn)]"
        : tone === "ok"
          ? "text-[color:var(--ok)]"
          : "text-[color:var(--fg)]";
  const dark = tone === "crit" ? "bar-crit" : tone === "warn" ? "bar-warn" : tone === "ok" ? "bar-ok" : "";
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="bar-label text-[9.5px] font-medium uppercase tracking-[0.1em] text-[color:var(--fg-3)]">
        {label}
      </span>
      <span className={`num bar-value text-[11.5px] font-medium ${light} ${dark}`}>{children}</span>
    </span>
  );
}

function Separator() {
  return <span aria-hidden="true" className="bar-sep h-3.5 w-px shrink-0 bg-[color:var(--line)]" />;
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
function DemoBar() {
  return (
    <header className="chrome-ui flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-[color:var(--line)] px-4 py-[7px]">
      <span className="text-[12.5px] font-semibold tracking-[0.02em]">SALVAGE</span>
      <span className="text-[11.5px] text-[color:var(--fg-2)]">
        Payment failure recovery for Indian merchants on Razorpay
      </span>
      <span className="ml-auto text-[11px] text-[color:var(--fg-3)]">
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
    <header
      className={`chrome-ui flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-[7px] ${
        killed ? "border-[color:var(--crit)] bg-[color:var(--crit-bg)]" : "border-[color:var(--line)] bg-[color:var(--bg)]"
      }`}
    >
      {/* Identity. The product name is a label in the corner, not a headline. */}
      <span className="flex items-baseline gap-2">
        <span className="text-[12.5px] font-semibold tracking-[0.02em]">SALVAGE</span>
        <span className="num bar-label text-[9.5px] font-medium uppercase tracking-[0.1em] text-[color:var(--fg-3)]">
          {env} &middot; sim
        </span>
      </span>

      <Separator />

      {/* The world this console is looking at. */}
      <Readout label={clockLabel}>
        {overview.data
          ? new Date(overview.data.now * 1000).toLocaleString("en-IN", {
              timeZone: "Asia/Kolkata",
              hour12: false,
            })
          : "..."}
      </Readout>
      <Readout label="stream" tone={stream === "disconnected" ? "crit" : "ink"}>
        {stream}
      </Readout>

      <Separator />

      {/* That world's current state. */}
      <Readout label="incidents" tone={open > 0 ? "crit" : "ok"}>
        {String(open).padStart(2, "0")}
      </Readout>
      <Readout label="model">{health.data?.llm_provider ?? "..."}</Readout>

      {killed && (
        <>
          <Separator />
          <span className="bar-crit text-[11px] font-semibold text-[color:var(--crit)]">
            Outbound actions suspended
          </span>
        </>
      )}

      <div className="ml-auto flex items-center gap-3">
        <label className="bar-label flex items-center gap-2 text-[9.5px] font-medium uppercase tracking-[0.1em] text-[color:var(--fg-3)]">
          token
          <input
            type="password"
            value={token ?? ""}
            onChange={(event) => setToken(event.target.value || null)}
            placeholder="SALVAGE_DASHBOARD_TOKEN"
            className="num w-44 border border-[color:var(--line-2)] px-2 py-[3px] text-[11px]"
          />
        </label>

        <ConfirmButton
          label={killed ? "Resume outbound actions" : "Suspend outbound actions"}
          confirmLabel={killed ? "Resume" : "Suspend"}
          tone={killed ? "green" : "red"}
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
        <div className="bar-crit w-full text-xs text-[color:var(--crit)]" role="alert">
          {describe(error)}
        </div>
      )}
    </header>
  );
}
