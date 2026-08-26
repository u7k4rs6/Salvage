import type { ReactNode } from "react";
import { describe } from "../../lib/api";

/**
 * Loading, empty and error on the dark surface.
 *
 * The console's shared primitives are drawn for the light frame the other six pages use, so the
 * Overview carries its own three. They are the same three states with the same contract: every
 * region that renders server data can be in exactly one of them, and none of them is optional.
 */

export function Loading({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="skeleton mb-2"
          style={{ width: `${100 - index * 9}%`, animationDelay: `${index * 90}ms` }}
        />
      ))}
    </div>
  );
}

export function Empty({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="py-10">
      <p className="body">{children}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorPanel({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div role="alert" className="error-block">
      <div className="microlabel" style={{ color: "var(--incident)" }}>
        Request failed
      </div>
      <div className="mono mt-1.5 break-words" style={{ fontSize: 12, color: "var(--text-2)" }}>
        {describe(error)}
      </div>
      {retry && (
        <button
          type="button"
          onClick={retry}
          className="focus-ring microlabel microlabel-ink lift mt-3 block"
        >
          Try again &rarr;
        </button>
      )}
    </div>
  );
}
