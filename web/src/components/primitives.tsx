import { useState, type ReactNode } from "react";
import { describe } from "../lib/api";

// The whole component vocabulary of the console. No component library (spec section 1); these
// seven primitives are what every page is built from.

export function Panel({
  title,
  subtitle,
  right,
  children,
  className = "",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`border border-neutral-300 bg-white ${className}`}>
      {(title || right) && (
        <header className="flex items-start justify-between gap-4 border-b border-neutral-200 px-4 py-2">
          <div>
            {title && <h2 className="text-sm font-semibold text-neutral-900">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-neutral-600">{subtitle}</p>}
          </div>
          {right && <div className="shrink-0">{right}</div>}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

type Tone = "neutral" | "red" | "amber" | "green" | "accent";

const TONES: Record<Tone, string> = {
  neutral: "bg-neutral-100 text-neutral-700 border-neutral-300",
  red: "bg-red-50 text-red-800 border-red-300",
  amber: "bg-amber-50 text-amber-800 border-amber-300",
  green: "bg-green-50 text-green-800 border-green-300",
  accent: "bg-accent-soft text-accent-hover border-accent",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-block whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] font-medium ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

/** Colour is never the only signal (spec section 7), so every state badge carries its own word. */
export function StatusBadge({ status }: { status: string }) {
  const tone: Tone =
    status === "open" || status === "recovering"
      ? "red"
      : status === "escalated" || status === "paused"
        ? "amber"
        : status === "closed"
          ? "neutral"
          : "neutral";
  return <Badge tone={tone}>{status}</Badge>;
}

export function Stat({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
}) {
  const colour =
    tone === "red"
      ? "text-red-700"
      : tone === "green"
        ? "text-green-700"
        : tone === "amber"
          ? "text-amber-700"
          : "text-neutral-900";
  return (
    <div className="border border-neutral-300 bg-white px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-neutral-600">{label}</div>
      <div className={`num mt-1 text-2xl font-semibold ${colour}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-neutral-600">{hint}</div>}
    </div>
  );
}

export function Table({
  columns,
  children,
  align = [],
}: {
  columns: string[];
  children: ReactNode;
  align?: ("left" | "right")[];
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-table">
        <thead>
          <tr className="border-b border-neutral-300 text-left text-neutral-600">
            {columns.map((column, index) => (
              <th
                key={column}
                scope="col"
                className={`cell-pad text-xs font-medium uppercase tracking-wide ${
                  align[index] === "right" ? "text-right" : ""
                }`}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Loading({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="mb-2 h-6 w-full animate-pulse rounded bg-neutral-100" />
      ))}
    </div>
  );
}

export function Empty({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="py-8 text-center">
      <p className="text-sm text-neutral-600">{children}</p>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorPanel({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div role="alert" className="border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
      <div className="font-medium">Request failed</div>
      <div className="num mt-1 break-words text-xs">{describe(error)}</div>
      {retry && (
        <button
          type="button"
          onClick={retry}
          className="mt-2 border border-red-300 bg-white px-2 py-1 text-xs hover:bg-red-100"
        >
          Try again
        </button>
      )}
    </div>
  );
}

/**
 * The three mandatory data-region states in one place (spec section 3), so a page cannot forget
 * one. Anything that renders server data goes through this.
 */
export function Region<T>({
  state,
  empty,
  children,
  rows = 4,
}: {
  state: { data: T | null; error: unknown; loading: boolean; reload: () => void };
  empty?: ReactNode;
  children: (data: T) => ReactNode;
  rows?: number;
}) {
  if (state.error) return <ErrorPanel error={state.error} retry={state.reload} />;
  if (state.loading && state.data === null) return <Loading rows={rows} />;
  if (state.data === null) return <Empty>{empty ?? "Nothing here yet."}</Empty>;
  return <>{children(state.data)}</>;
}

export function Disclosure({
  summary,
  children,
  className = "",
}: {
  summary: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <details className={`group ${className}`}>
      <summary className="cursor-pointer select-none text-xs text-accent hover:text-accent-hover">
        {summary}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

export function Code({ children }: { children: ReactNode }) {
  return (
    <pre className="num max-h-96 overflow-auto whitespace-pre-wrap break-words border border-neutral-200 bg-neutral-50 p-3 text-xs text-neutral-800">
      {children}
    </pre>
  );
}

/**
 * A button that asks once before doing something, and requires a note when the caller says so.
 * The two confirmations the spec allows as modals are built from this.
 */
export function ConfirmButton({
  label,
  confirmLabel,
  prompt,
  requireNote = false,
  notePlaceholder = "Reason",
  tone = "accent",
  disabled = false,
  disabledReason,
  onConfirm,
}: {
  label: string;
  confirmLabel?: string;
  prompt: string;
  requireNote?: boolean;
  notePlaceholder?: string;
  tone?: "accent" | "red" | "green";
  disabled?: boolean;
  disabledReason?: string;
  onConfirm: (note: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const colour =
    tone === "red"
      ? "border-red-400 bg-red-50 text-red-800 hover:bg-red-100"
      : tone === "green"
        ? "border-green-400 bg-green-50 text-green-800 hover:bg-green-100"
        : "border-accent bg-accent-soft text-accent-hover hover:bg-teal-100";

  if (!open) {
    return (
      <span>
        <button
          type="button"
          disabled={disabled}
          title={disabled ? disabledReason : undefined}
          onClick={() => {
            setError(null);
            setOpen(true);
          }}
          className={`border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50 ${colour}`}
        >
          {disabled && <span aria-hidden="true">&#128274; </span>}
          {label}
        </button>
        {disabled && disabledReason && (
          <span className="ml-2 text-xs text-neutral-600">{disabledReason}</span>
        )}
      </span>
    );
  }

  return (
    <div className="border border-neutral-300 bg-neutral-50 p-3">
      <p className="text-xs text-neutral-800">{prompt}</p>
      {requireNote && (
        <input
          autoFocus
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder={notePlaceholder}
          className="mt-2 w-full border border-neutral-300 px-2 py-1 text-xs"
        />
      )}
      {error !== null && (
        <div className="mt-2 text-xs text-red-700" role="alert">
          {describe(error)}
        </div>
      )}
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          disabled={busy || (requireNote && note.trim().length === 0)}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await onConfirm(note.trim());
              setOpen(false);
              setNote("");
            } catch (cause) {
              // The note is deliberately kept so a failed decision can be retried (spec 4.3).
              setError(cause);
            } finally {
              setBusy(false);
            }
          }}
          className={`border px-2 py-1 text-xs disabled:opacity-50 ${colour}`}
        >
          {busy ? "Working" : (confirmLabel ?? "Confirm")}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="border border-neutral-300 bg-white px-2 py-1 text-xs hover:bg-neutral-100"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
