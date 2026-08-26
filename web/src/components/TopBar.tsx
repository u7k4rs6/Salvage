import { useState, type ReactNode } from "react";
import { post, describe } from "../lib/api";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { useStream, useStreamState } from "../lib/useStream";
import { ConfirmButton } from "./primitives";
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
      ? "text-red-700"
      : tone === "warn"
        ? "text-amber-700"
        : tone === "ok"
          ? "text-green-700"
          : "text-neutral-900";
  const dark = tone === "crit" ? "bar-crit" : tone === "warn" ? "bar-warn" : tone === "ok" ? "bar-ok" : "";
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="bar-label text-[9.5px] font-medium uppercase tracking-[0.1em] text-neutral-400">
        {label}
      </span>
      <span className={`num bar-value text-[11.5px] font-medium ${light} ${dark}`}>{children}</span>
    </span>
  );
}

function Separator() {
  return <span aria-hidden="true" className="bar-sep h-3.5 w-px shrink-0 bg-neutral-200" />;
}

export function TopBar() {
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
        killed ? "border-red-500 bg-red-50" : "border-neutral-200 bg-white"
      }`}
    >
      {/* Identity. The product name is a label in the corner, not a headline. */}
      <span className="flex items-baseline gap-2">
        <span className="text-[12.5px] font-semibold tracking-[0.02em]">SALVAGE</span>
        <span className="num bar-label text-[9.5px] font-medium uppercase tracking-[0.1em] text-neutral-400">
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
          <span className="bar-crit text-[11px] font-semibold text-red-700">
            Outbound actions suspended
          </span>
        </>
      )}

      <div className="ml-auto flex items-center gap-3">
        <label className="bar-label flex items-center gap-2 text-[9.5px] font-medium uppercase tracking-[0.1em] text-neutral-400">
          token
          <input
            type="password"
            value={token ?? ""}
            onChange={(event) => setToken(event.target.value || null)}
            placeholder="SALVAGE_DASHBOARD_TOKEN"
            className="num w-44 border border-neutral-300 px-2 py-[3px] text-[11px]"
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
        <div className="bar-crit w-full text-xs text-red-700" role="alert">
          {describe(error)}
        </div>
      )}
    </header>
  );
}
