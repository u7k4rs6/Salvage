import type { ReactNode } from "react";
import { describe } from "../../lib/api";

/**
 * Loading, empty and error on the dark surface.
 *
 * The console's shared primitives are drawn for the light frame the other six pages use, so this
 * page carries its own three. Same contract: every region that renders server data is in exactly
 * one of these states, and none of them is optional.
 */

export function Loading({ rows = 3, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="skeleton mb-2"
          style={{ width: `${96 - index * 11}%`, animationDelay: `${index * 80}ms` }}
        />
      ))}
    </div>
  );
}

export function Empty({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="py-6">
      <p className="txt">{children}</p>
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function ErrorPanel({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div role="alert" className="notice notice-danger">
      <div className="notice-label">Request failed</div>
      <div className="mono mid mt-1.5 break-words text-[length:var(--fs-meta)]">{describe(error)}</div>
      {retry && (
        <button type="button" onClick={retry} className="link focus-ring lbl lbl-2 mt-2.5 block">
          Retry &rarr;
        </button>
      )}
    </div>
  );
}
