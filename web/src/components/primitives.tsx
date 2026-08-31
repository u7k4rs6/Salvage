import { createContext, useContext, useState, type ReactNode } from "react";
import { describe } from "../lib/api";

// The whole component vocabulary of the console. No component library (spec section 1); these
// seven primitives are what every page is built from.

export function Panel({
  title,
  subtitle,
  right,
  children,
  className = "",
  flush = false,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  /** For a panel whose body is a table, which brings its own padding. */
  flush?: boolean;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || right) && (
        <header className="panel-head">
          <div className="min-w-0">
            {title && <h2 className="section-title">{title}</h2>}
            {subtitle && <p className="panel-note">{subtitle}</p>}
          </div>
          {right && <div className="shrink-0">{right}</div>}
        </header>
      )}
      <div className={flush ? "panel-flush" : "panel-body"}>{children}</div>
    </section>
  );
}

type Tone = "neutral" | "danger" | "warning" | "success" | "accent";

const BADGE_CLASS: Record<Tone, string> = {
  neutral: "",
  danger: "badge-danger",
  warning: "badge-warning",
  success: "badge-success",
  accent: "badge-accent",
};

/**
 * One badge shape for the whole console. Only the colour varies, and only with meaning.
 *
 * Colour is never the only signal: the badge always carries its own word, so a reader who cannot
 * separate the hues still reads the state.
 */
export function Badge({
  tone = "neutral",
  dot = true,
  children,
}: {
  tone?: Tone;
  dot?: boolean;
  children: ReactNode;
}) {
  return (
    <span className={`badge ${BADGE_CLASS[tone]}`}>
      {dot && tone !== "neutral" && <span className="badge-dot" aria-hidden="true" />}
      {children}
    </span>
  );
}

/** Incident and case states, mapped to the one badge. */
export function StatusBadge({ status }: { status: string }) {
  const tone: Tone =
    status === "open" || status === "recovering"
      ? "danger"
      : status === "escalated" || status === "paused"
        ? "warning"
        : status === "closed"
          ? "success"
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
    tone === "danger"
      ? "text-[color:var(--danger)]"
      : tone === "success"
        ? "text-[color:var(--success)]"
        : tone === "warning"
          ? "text-[color:var(--warning)]"
          : "text-[color:var(--text-primary)]";
  return (
    <div className="border border-[color:var(--border-strong)] bg-[color:var(--surface)] px-4 py-3">
      <div className="text-[length:var(--fs-meta)] uppercase tracking-wide text-[color:var(--text-secondary)]">{label}</div>
      <div className={`num mt-1 text-[length:var(--fs-page-title)] font-semibold ${colour}`}>{value}</div>
      {hint && <div className="mt-0.5 text-[length:var(--fs-meta)] text-[color:var(--text-secondary)]">{hint}</div>}
    </div>
  );
}

/** How a column behaves. Declared once per column and inherited by the header and every cell. */
export type ColumnAlign = "text" | "num" | "status";

export interface Column {
  key: string;
  label: ReactNode;
  align?: ColumnAlign;
  /** A fixed width where the column should not breathe, such as a timestamp or a sequence. */
  width?: string;
}

const ALIGN_CLASS: Record<ColumnAlign, string> = {
  text: "col-text",
  num: "col-num",
  status: "col-status",
};

/**
 * The console's one data table.
 *
 * Alignment is a property of the column, not of the cell: `columns` declares it once and `Cell`
 * reads it back out, so a header and the values under it cannot disagree. That mismatch, a
 * right-aligned header over left-aligned numbers, is the commonest way a table looks wrong, and
 * this shape makes it unrepresentable rather than merely discouraged.
 */
export function Table({
  columns,
  children,
  minWidth,
}: {
  columns: Column[];
  children: ReactNode;
  /**
   * The width below which the columns stop being readable and the wrapper should scroll instead.
   * Percentage columns divide whatever they are given, so a table of long identifiers needs a
   * floor: without one the shares resolve against a narrow viewport and a timestamp breaks across
   * three lines. Defaults to the 46rem in `.dt-wrap > .dt`.
   */
  minWidth?: string;
}) {
  return (
    <TableColumns.Provider value={columns}>
      <div className="dt-wrap">
        <table className="dt" style={minWidth ? { minWidth } : undefined}>
          <colgroup>
            {columns.map((column) => (
              <col key={column.key} style={column.width ? { width: column.width } : undefined} />
            ))}
          </colgroup>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column.key} scope="col" className={ALIGN_CLASS[column.align ?? "text"]}>
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>{children}</tbody>
        </table>
      </div>
    </TableColumns.Provider>
  );
}

const TableColumns = createContext<Column[]>([]);

/**
 * One cell, aligned by the column it sits in rather than by what its author felt like.
 *
 * `column` is the key from the table's column list. Passing an index would work until somebody
 * reorders the columns and every cell silently takes the wrong alignment.
 */
export function Cell({
  column,
  children,
  className = "",
  ...rest
}: {
  column: string;
  children?: ReactNode;
  className?: string;
} & React.TdHTMLAttributes<HTMLTableCellElement>) {
  const columns = useContext(TableColumns);
  const found = columns.find((entry) => entry.key === column);
  return (
    <td className={`${ALIGN_CLASS[found?.align ?? "text"]} ${className}`} {...rest}>
      {children}
    </td>
  );
}

/** A primary figure with quieter figures under it, sharing the column's edge. */
export function Metric({
  value,
  secondary,
}: {
  value: ReactNode;
  secondary?: ReactNode[];
}) {
  return (
    <span className="dt-metric">
      <span className="dt-metric-primary">{value}</span>
      {secondary?.filter(Boolean).map((line, index) => (
        <span key={index} className="dt-metric-secondary">
          {line}
        </span>
      ))}
    </span>
  );
}

export function Loading({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="mb-2 h-6 w-full animate-pulse rounded bg-[color:var(--surface-raised)]" />
      ))}
    </div>
  );
}

/**
 * An empty state, on the same left edge as the content that will replace it.
 *
 * Centred in a surface a thousand pixels wide, one short line read as a void with a caption in the
 * middle of it. It sits where the first row of data will sit, so the panel does not change shape
 * when the data arrives.
 */
export function Empty({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="px-5 py-6">
      <p className="text-[length:var(--fs-meta)] text-[color:var(--text-muted)]">{children}</p>
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function ErrorPanel({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div role="alert" className="notice notice-danger">
      <div className="notice-label">Request failed</div>
      <div className="num notice-body break-words">{describe(error)}</div>
      {retry && (
        <button
          type="button"
          onClick={retry}
          className="btn btn-danger focus-ring mt-3"
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
      <summary className="cursor-pointer select-none text-[length:var(--fs-meta)] text-[color:var(--info)] hover:text-[color:var(--text-primary)]">
        {summary}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

export function Code({ children }: { children: ReactNode }) {
  return (
    <pre className="num max-h-96 overflow-auto whitespace-pre-wrap break-words border border-[color:var(--border)] bg-[color:var(--surface-raised)] p-3 text-[length:var(--fs-meta)] text-[color:var(--text-primary)]">
      {children}
    </pre>
  );
}

/**
 * A button that asks once before doing something, and requires a note when the caller says so.
 * The two confirmations the spec allows as modals are built from this.
 */
/**
 * A control that asks before it acts, and where the product requires it, asks for a written note.
 *
 * The note is not decoration: an escalation decision is a person taking responsibility for what
 * the agent would not do alone, and the note is what makes that decision auditable afterwards.
 * The confirm stays disabled until one is written.
 */
export function ConfirmButton({
  label,
  confirmLabel = "Confirm",
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
  tone?: "accent" | "danger" | "success";
  disabled?: boolean;
  disabledReason?: string;
  onConfirm: (note: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (!open) {
    return (
      <span className="inline-flex items-center gap-2">
        <button
          type="button"
          disabled={disabled}
          title={disabled ? disabledReason : undefined}
          onClick={() => {
            setError(null);
            setOpen(true);
          }}
          className={`btn focus-ring ${tone === "danger" ? "btn-danger" : ""}`}
        >
          {label}
        </button>
        {disabled && disabledReason && (
          <span className="text-[length:var(--fs-micro)] text-[color:var(--text-muted)]">
            {disabledReason}
          </span>
        )}
      </span>
    );
  }

  return (
    <div className="rounded-[var(--radius-sm)] border border-[color:var(--border-strong)] bg-[color:var(--surface-raised)] p-4">
      <p className=" text-[length:var(--fs-meta)] leading-[var(--lh-normal)] text-[color:var(--text-primary)]">
        {prompt}
      </p>
      {requireNote && (
        <input
          autoFocus
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder={notePlaceholder}
          className="field mt-3 w-full"
        />
      )}
      {error !== null && (
        <div
          className="mt-3 text-[length:var(--fs-meta)] text-[color:var(--danger)]"
          role="alert"
        >
          {describe(error)}
        </div>
      )}
      <div className="mt-3 flex gap-2">
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
              setError(cause);
            } finally {
              setBusy(false);
            }
          }}
          className={`btn focus-ring ${tone === "danger" ? "btn-danger" : "btn-primary"}`}
        >
          {busy ? "Working" : confirmLabel}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setOpen(false);
            setNote("");
            setError(null);
          }}
          className="btn btn-ghost focus-ring"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
