import { Decoded } from "./Decoded";

/**
 * A number with its scope attached.
 *
 * Microlabel above, number, scope note below. Every figure names the population and the window
 * it covers, because the four in the stat row do not share one and two of them cannot be divided
 * by each other. A figure without a scope note is a figure a reader will misread.
 *
 * The number decodes when it changes, which on this page means when the window advances. It does
 * not decode on first paint; `useScramble` holds the first value still.
 */

type Tone = "ink" | "incident" | "recovered" | "pending" | "muted";

const TONE: Record<Tone, string> = {
  ink: "var(--text)",
  incident: "var(--incident)",
  recovered: "var(--recovered)",
  pending: "var(--pending)",
  muted: "var(--text-3)",
};

export function Figure({
  value,
  label,
  scope,
  tone = "ink",
  size = "stat",
  prefix,
  decode = true,
}: {
  value: string;
  label: string;
  scope?: string;
  tone?: Tone;
  size?: "hero" | "stat";
  prefix?: string;
  decode?: boolean;
}) {
  return (
    <div>
      <div className="microlabel">{label}</div>
      <div
        className={`display ${size === "hero" ? "hero-stat" : "stat-2"} mt-3`}
        style={{ color: TONE[tone] }}
      >
        {prefix && (
          <span className="align-top" style={{ fontSize: "0.38em", lineHeight: 1.6 }}>
            {prefix}
          </span>
        )}
        <Decoded value={value} enabled={decode} />
      </div>
      {scope && <div className="scope mt-3 max-w-[22rem]">{scope}</div>}
    </div>
  );
}
