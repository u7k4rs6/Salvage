import { useState } from "react";
import { post, describe } from "../lib/api";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";
import { useStream, useStreamConnected } from "../lib/useStream";
import { Badge, ConfirmButton } from "./primitives";
import type { Health, Overview } from "../lib/types";

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
  const connected = useStreamConnected();
  const [error, setError] = useState<unknown>(null);

  useStream(["incident.opened", "incident.closed", "sim.finished"], () => overview.reload());

  const killed = health.data?.kill_switch ?? false;
  const open = overview.data?.incidents.length ?? 0;
  const clock = overview.data?.clock === "sim" ? "sim clock" : "wall clock";

  return (
    <header
      className={`flex flex-wrap items-center gap-4 border-b px-4 py-2 ${
        killed ? "border-red-500 bg-red-50" : "border-neutral-300 bg-neutral-50"
      }`}
    >
      <span className="text-sm font-semibold tracking-tight">Salvage</span>

      <Badge tone={health.data?.env === "demo" ? "amber" : "neutral"}>
        {health.data?.env ?? "..."}
      </Badge>

      <span className="num text-xs text-neutral-600">
        {clock}
        {overview.data ? ` ${new Date(overview.data.now * 1000).toLocaleString("en-IN", {
          timeZone: "Asia/Kolkata",
          hour12: false,
        })}` : ""}
      </span>

      <span className="text-xs">
        <span className="text-neutral-600">active incidents </span>
        <span className={`num font-semibold ${open > 0 ? "text-red-700" : "text-neutral-900"}`}>
          {open}
        </span>
      </span>

      <span className="text-xs text-neutral-600">
        stream {connected ? "connected" : "disconnected"}
      </span>

      <span className="text-xs text-neutral-600">
        model {health.data?.llm_provider ?? "..."}
      </span>

      {killed && (
        <span className="text-xs font-semibold text-red-700">Outbound actions suspended</span>
      )}

      <div className="ml-auto flex items-center gap-3">
        <label className="flex items-center gap-2 text-xs text-neutral-700">
          token
          <input
            type="password"
            value={token ?? ""}
            onChange={(event) => setToken(event.target.value || null)}
            placeholder="SALVAGE_DASHBOARD_TOKEN"
            className="num w-56 border border-neutral-300 px-2 py-1 text-xs"
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
