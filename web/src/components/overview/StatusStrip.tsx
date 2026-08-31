import { Link } from "react-router-dom";
import { Metric, Methodology } from "./Chrome";
import {
  SEVERITY_CLASS,
  baselineSuccess,
  deviationArrow,
  deviationPoints,
  deviationSeverity,
  formatPoints,
} from "../../lib/health";
import { count, percent, rupees, timeOnly } from "../../lib/format";
import type { Overview } from "../../lib/types";

/**
 * Current operational state, on one baseline.
 *
 * Payment success is the metric that decides whether anything else on the page matters, so it is
 * the only one set large. The other three are secondary and are sized as such. None of the
 * figures is coloured: a number is not a severity. The colour sits on the deviation, which is a
 * comparison and therefore can be good or bad.
 *
 * Two windows appear here and both are named. The headline rate covers the last 60 minutes, which
 * is the operator's sense of "now". The deviation is the merchant-wide key in the detector's own
 * 15 minute window against its seven-day baseline, which is the only baseline the API carries.
 * They are not combined into a single number, because subtracting one window's rate from another
 * window's baseline would be arithmetic on two different populations.
 */
export function StatusStrip({ data }: { data: Overview }) {
  const merchant = data.segments.find((segment) => segment.key === "all") ?? null;
  const points = merchant ? deviationPoints(merchant) : null;
  const severity = points === null ? "idle" : deviationSeverity(points);

  return (
    <div>
      <div className="metrics">
        <Metric
          label="Payment success"
          size="xl"
          value={percent(data.stats.success_rate)}
          delta={
            merchant && points !== null ? (
              <span className={`mono text-[13px] ${SEVERITY_CLASS[severity]}`}>
                {deviationArrow(points)} {formatPoints(points)} vs{" "}
                {percent(baselineSuccess(merchant))} baseline
              </span>
            ) : undefined
          }
          meta={
            <span className="note mono">
              {count(data.stats.attempts_last_hour)} attempts &middot; 60 min &middot; deviation is
              merchant-wide on the detector&rsquo;s 15m window
            </span>
          }
        />

        <Metric
          label="Exposure"
          value={<>&#8377;{rupees(data.stats.at_risk_amount)}</>}
          definition="Unpaid orders during active incident windows."
        />

        <Metric
          label="Recovered"
          value={<>&#8377;{rupees(data.stats.recovered_amount)}</>}
          definition="Orders rerouted through Salvage link and steer."
        />

        <Metric
          label="Attempts"
          value={count(data.stats.attempts_last_hour)}
          definition={`Payment attempts to ${timeOnly(data.window.end)}.`}
        />
      </div>

      <Methodology label="Methodology">
        Exposure and recovered are not two ends of one number and their ratio is not a recovery
        rate. Exposure counts orders unpaid inside a single detection window; recovered spans each
        incident&rsquo;s whole life over a population that is not the same set. The measured rate,
        where numerator and denominator share a set, is{" "}
        <Link to="/results" className="link focus-ring underline underline-offset-2">
          at_risk_recovery_rate on Results
        </Link>
        . Recovered excludes organic recovery. Deviation compares the merchant-wide key against its
        trailing seven-day baseline for the same hour band.
      </Methodology>
    </div>
  );
}
