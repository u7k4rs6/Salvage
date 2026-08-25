// Amounts arrive in paise and times in Unix seconds; both are formatted here and nowhere else
// (docs/04_FRONTEND_SPEC.md section 5).

const IST = "Asia/Kolkata";

/** Paise to rupees with Indian digit grouping and two decimals. */
export function rupees(paise: number | null | undefined): string {
  if (paise === null || paise === undefined || Number.isNaN(paise)) return "-";
  return (paise / 100).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function rupeesShort(paise: number | null | undefined): string {
  if (paise === null || paise === undefined || Number.isNaN(paise)) return "-";
  const rupeeValue = paise / 100;
  if (rupeeValue >= 10000000) return `${(rupeeValue / 10000000).toFixed(2)} Cr`;
  if (rupeeValue >= 100000) return `${(rupeeValue / 100000).toFixed(2)} L`;
  return rupees(paise);
}

export function count(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toLocaleString("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${(value * 100).toFixed(digits)}%`;
}

/** Unix seconds in IST. The clock label says whether this is sim time or wall time. */
export function timestamp(seconds: number | null | undefined): string {
  if (!seconds) return "-";
  return new Date(seconds * 1000).toLocaleString("en-IN", {
    timeZone: IST,
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function timeOnly(seconds: number | null | undefined): string {
  if (!seconds) return "-";
  return new Date(seconds * 1000).toLocaleTimeString("en-IN", {
    timeZone: IST,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function shortHash(value: string | null | undefined, length = 12): string {
  if (!value) return "-";
  return value.slice(0, length);
}

/** Segment keys are method[:dimension:value]. Rendered as the human reads them. */
export function segmentLabel(key: string): string {
  if (key === "all") return "All methods";
  const parts = key.split(":");
  if (parts.length === 1) return parts[0].toUpperCase();
  return `${parts[0].toUpperCase()} / ${parts[2]}`;
}

export function causeLabel(cause: string | null | undefined): string {
  if (!cause) return "-";
  return cause.replace(/_/g, " ");
}

/**
 * A baseline policy opens one synthetic incident to hang its cases on, so the recovery accounting
 * is comparable with the agent's. The detector did not open it and nothing diagnosed it, and a
 * causeless open incident on the Overview would read as a detector bug rather than as what it is.
 */
export function isSyntheticIncident(id: string): boolean {
  return id.endsWith("_baseline");
}
