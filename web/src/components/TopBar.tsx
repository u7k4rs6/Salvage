import { useState, type ReactNode } from "react";
import { post, describe } from "../lib/api";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { useStream, useStreamState } from "../lib/useStream";
import { Badge, ConfirmButton } from "./primitives";
import type { Health, Overview } from "../lib/types";

/** One compact label-and-value pair. The top bar is a strip of these, not a row of cards. */
function Readout({
  label,
  tone = "ink",
  children,
}: {
  label: string;
  tone?: "ink" | "red";
  children: ReactNode;
}) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-[9.5px] font-semibold uppercase tracking-[0.12em] text-neutral-400">
        {label}
      </span>
      <span
        className={`num text-[11.5px] font-medium ${tone === "red" ? "text-red-700" : "text-neutral-900"}`}
      >
        {children}
      </span>
    </span>
  );
}

/**
 * Environment, clock, active incident count, kill switch, token entry (spec section 2).
 *
 * The kill switch is the one control that is always visible from every page, because the point of
 * it is that a human can stop the agent without finding the right screen first.
 */
export function TopBar() {
  const { token, setToken } = useSession();
  const health = useApi<Health>("/api/health");
  const overview = useApi<Overview>("/api/overview");
  const stream = useStreamState();
  const [error, setError] = useState<unknown>(null);

  useStream(["incident.opened", "incident.closed", "sim.finished"], () => overview.reload());

  const killed = health.data?.kill_switch ?? false;
  const open = overview.data?.incidents.length ?? 0;
  const clock = overview.data?.clock === "sim" ? "sim clock" : "wall clock";

  return (
    <header
      className={`chrome-ui flex flex-wrap items-center gap-x-5 gap-y-2 border-b px-4 py-2 ${
        killed ? "border-red-500 bg-red-50" : "border-neutral-200 bg-white"
      }`}
    >
      <span className="text-[13px] font-semibold tracking-[-0.01em]">Salvage</span>

      <Badge tone={health.data?.env === "demo" ? "amber" : "neutral"}>
        {health.data?.env ?? "..."}
      </Badge>

      <Readout label={clock}>
        {overview.data
          ? new Date(overview.data.now * 1000).toLocaleString("en-IN", {
              timeZone: "Asia/Kolkata",
              hour12: false,
            })
          : "..."}
      </Readout>

      <Readout label="active incidents" tone={open > 0 ? "red" : "ink"}>
        {open}
      </Readout>

      <Readout label="stream" tone={stream === "disconnected" ? "red" : "ink"}>
        {stream}
      </Readout>

      <Readout label="model">{health.data?.llm_provider ?? "..."}</Readout>

      {killed && (
        <span className="text-xs font-semibold text-red-700">Outbound actions suspended</span>
      )}

      <div className="ml-auto flex items-center gap-3">
        <label className="flex items-center gap-2 text-[9.5px] font-semibold uppercase tracking-[0.12em] text-neutral-400">
          token
          <input
            type="password"
            value={token ?? ""}
            onChange={(event) => setToken(event.target.value || null)}
            placeholder="SALVAGE_DASHBOARD_TOKEN"
            className="num w-48 border border-neutral-300 px-2 py-[3px] text-[11px]"
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
        <div className="w-full text-xs text-red-700" role="alert">
          {describe(error)}
        </div>
      )}
    </header>
  );
}
