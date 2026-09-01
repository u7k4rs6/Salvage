import type { ReactNode } from "react";
import { SEVERITY_CLASS, type Severity } from "../../lib/health";

/**
 * Section furniture and the status chip.
 *
 * A section is a rule and a label, not a floating card. Panels exist in this file too but are
 * used only where grouping is load-bearing, because a page made of rounded rectangles reads as a
 * collection of widgets rather than as one control plane.
 */

export function Section({
  title,
  right,
  tight,
  anchor,
  children,
}: {
  title: string;
  right?: ReactNode;
  tight?: boolean;
  /**
   * A name the commentary layer can point at. Nothing else reads it, and a section without one is
   * simply never annotated, which is how a region with no data behind it stays unannotated.
   */
  anchor?: string;
  children: ReactNode;
}) {
  return (
    <section className={`section${tight ? " section-tight" : ""}`} data-anchor={anchor}>
      <div className="section-head">
        <h2 className="section-title">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

/** Colour is never the only signal: every chip carries its own word. */
export function Chip({
  severity,
  children,
  flat,
}: {
  severity?: Severity;
  children: ReactNode;
  flat?: boolean;
}) {
  if (flat || !severity) return <span className="chip chip-flat">{children}</span>;
  return (
    <span className={`chip ${SEVERITY_CLASS[severity]}`}>
      <span className="dot" aria-hidden="true" />
      {children}
    </span>
  );
}

/**
 * One metric: label, value, and the definition underneath.
 *
 * The definition is one line and it is the whole explanation. Methodology that does not fit on
 * one line belongs behind the disclosure at the foot of the section, not in the middle of the
 * numbers, because the dashboard is observational and not educational.
 */
export function Metric({
  label,
  value,
  size = "lg",
  delta,
  definition,
  meta,
}: {
  label: string;
  value: ReactNode;
  size?: "xl" | "lg";
  delta?: ReactNode;
  definition?: string;
  meta?: ReactNode;
}) {
  return (
    <div className="metric">
      <div className="lbl">{label}</div>
      <div className={`${size === "xl" ? "fig-xl" : "fig-lg"} mt-2`}>{value}</div>
      {(delta || meta) && (
        <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          {delta}
          {meta}
        </div>
      )}
      {definition && <div className="note mt-2 max-w-[24rem]">{definition}</div>}
    </div>
  );
}

/**
 * Methodology, folded away.
 *
 * The caveat that exposure and recovered cannot be divided by each other is true and it matters,
 * but it is a footnote about how two numbers are computed, and on the surface of an incident
 * dashboard it was three lines of prose between the reader and the incident. It lives here.
 */
export function Methodology({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details className="mt-4 group">
      <summary className="lbl focus-ring cursor-pointer list-none hover:text-[color:var(--text-secondary)]">
        {label}
      </summary>
      <div className="note mt-2 border-l border-[color:var(--border)] pl-3">{children}</div>
    </details>
  );
}
