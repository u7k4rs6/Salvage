import type { Distribution } from "../lib/types";
import { percent } from "../lib/format";

/**
 * Window against baseline, side by side (spec 4.2). Bars rather than numbers alone, because the
 * shape of the shift is the evidence: a fault moves mass from one bucket to another, and that is
 * visible instantly and hard to read off a table.
 */
export function DistributionPair({
  title,
  distribution,
}: {
  title: string;
  distribution: Distribution;
}) {
  const keys = Array.from(
    new Set([...Object.keys(distribution.window), ...Object.keys(distribution.baseline)]),
  ).sort(
    (left, right) =>
      (distribution.window[right] ?? 0) - (distribution.window[left] ?? 0) ||
      left.localeCompare(right),
  );

  return (
    <div>
      <h4 className="text-xs font-medium uppercase tracking-wide text-neutral-600">{title}</h4>
      <table className="mt-1 w-full text-table">
        <thead>
          <tr className="text-left text-[11px] text-neutral-500">
            <th scope="col" className="py-0.5 font-normal">
              bucket
            </th>
            <th scope="col" className="py-0.5 font-normal">
              window
            </th>
            <th scope="col" className="py-0.5 font-normal">
              baseline
            </th>
          </tr>
        </thead>
        <tbody>
          {keys.map((key) => {
            const now = distribution.window[key] ?? 0;
            const before = distribution.baseline[key] ?? 0;
            const moved = now - before;
            return (
              <tr key={key} className="border-t border-neutral-100">
                <td className="num py-0.5 pr-2 text-[11px] text-neutral-800">{key}</td>
                <td className="w-1/3 py-0.5 pr-2">
                  <div className="flex items-center gap-1">
                    <div
                      className={`h-2 ${moved > 0.05 ? "bg-red-500" : "bg-neutral-400"}`}
                      style={{ width: `${Math.round(now * 100)}%` }}
                    />
                    <span className="num text-[10px] text-neutral-600">{percent(now, 0)}</span>
                  </div>
                </td>
                <td className="w-1/3 py-0.5">
                  <div className="flex items-center gap-1">
                    <div
                      className="h-2 bg-neutral-300"
                      style={{ width: `${Math.round(before * 100)}%` }}
                    />
                    <span className="num text-[10px] text-neutral-500">{percent(before, 0)}</span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
