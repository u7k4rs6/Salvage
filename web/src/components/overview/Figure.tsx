import type { ReactNode } from "react";

/**
 * A number with its scope attached.
 *
 * Every figure on this page names the population and the window it covers, because three of the
 * four headline numbers cover different ones. Two of them cannot be divided by each other, and a
 * reader who is not told the scope will try.
 */
export function Figure({
  value,
  label,
  scope,
  tone = "ink",
  size = "lg",
  prefix,
  suffix,
}: {
  value: ReactNode;
  label: string;
  scope?: string;
  tone?: "ink" | "incident" | "recover";
  size?: "xl" | "lg" | "md";
  prefix?: string;
  suffix?: string;
}) {
  const colour =
    tone === "incident"
      ? "var(--incident)"
      : tone === "recover"
        ? "var(--recover)"
        : "var(--ink)";
  const type =
    size === "xl"
      ? "text-[clamp(3.5rem,7vw,5.75rem)]"
      : size === "lg"
        ? "text-[clamp(2rem,3.4vw,3rem)]"
        : "text-[clamp(1.5rem,2.2vw,2rem)]";

  return (
    <div>
      <div className={`display ${type} tabular-nums`} style={{ color: colour }}>
        {prefix && <span className="align-top text-[0.42em] font-600">{prefix}</span>}
        {value}
        {suffix && <span className="text-[0.44em]">{suffix}</span>}
      </div>
      <div className="label label-ink mt-2">{label}</div>
      {scope && <div className="label mt-1 normal-case tracking-normal text-[10.5px]">{scope}</div>}
    </div>
  );
}
