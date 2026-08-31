// Response shapes, transcribed from salvage/api/*.py. Only the fields the console reads.

export interface Segment {
  key: string;
  method: string;
  instrument: string;
  attempts: number;
  failures: number;
  rate: number;
  failure_rate: number;
  baseline: number;
  incident_id: string | null;
}

export interface IncidentSummary {
  id: string;
  segment_key: string;
  affected_scope: string[];
  opened_at: number;
  closed_at: number | null;
  status: string;
  rules_cause: string | null;
  llm_cause: string | null;
  root_cause: string | null;
  confidence: number | null;
  at_risk_amount: number;
  recovered_amount: number;
  cases: number;
  actions: number;
  escalated: boolean;
}

export interface Overview {
  clock: string;
  now: number;
  window: { start: number; end: number };
  segments: Segment[];
  incidents: IncidentSummary[];
  series: { t: number; attempts: number; failures: number }[];
  stats: {
    attempts_last_hour: number;
    success_rate: number | null;
    at_risk_amount: number;
    recovered_amount: number;
  };
}

export interface IncidentList {
  clock: string;
  total: number;
  limit: number;
  offset: number;
  incidents: IncidentSummary[];
}

export interface Distribution {
  window: Record<string, number>;
  baseline: Record<string, number>;
}

export interface Evidence {
  segment_key: string;
  window_start: number;
  window_end: number;
  attempts: number;
  failures: number;
  rate: number;
  baseline_rate: number;
  excess_failures: number;
  error_source_dist: Distribution;
  error_step_dist: Distribution;
  error_reason_dist: Distribution;
  error_code_top5: string[];
  sample_descriptions: string[];
  // Segment key to a one-word health verdict, exactly as the evidence packet carries it. The
  // packet gives the model a verdict rather than a rate, and the page shows what the model saw.
  sibling_segments: Record<string, string>;
  share_of_merchant_volume: number;
  minutes_since_onset: number;
  trend: string;
  merchant_config_changed_recently: boolean;
  affected_scope: string[];
}

export interface Diagnosis {
  rules: string | null;
  llm: string | null;
  reconciled: string | null;
  confidence: number | null;
  agreed: boolean;
  rationale: string | null;
  rules_detail: string | null;
  escalate: boolean;
  escalation_reason: string | null;
  prompt: string | null;
  raw_response: string | null;
}

export interface GateResult {
  rule: string;
  passed: boolean;
  detail: string;
}

export interface PlannedAction {
  id: string;
  type: string;
  case_id: string | null;
  status: string;
  params: Record<string, unknown>;
  gate: GateResult[];
}

export interface Plan {
  proposed: { type: string; scope: string; params: Record<string, unknown> }[];
  rationale: string | null;
  actions: PlannedAction[];
}

export interface RecoveryCase {
  id: string;
  order_id: string;
  ref_hash: string;
  amount: number;
  state: string;
  nudges: number;
  link_id: string | null;
  next_action_at: number | null;
  outcome: string | null;
}

export interface LedgerEntry {
  seq: number;
  ts: number;
  kind: string;
  ref_type: string;
  ref_id: string;
  hash: string;
  prev_hash?: string;
  payload: Record<string, unknown>;
}

export interface IncidentDetail {
  clock: string;
  incident: IncidentSummary;
  evidence: Evidence | null;
  diagnosis: Diagnosis | null;
  plan: Plan;
  cases: RecoveryCase[];
  timeline: LedgerEntry[];
}

export interface Escalation {
  id: string;
  incident_id: string;
  created_at: number;
  reason: string;
  evidence: Record<string, unknown>;
  proposed_action: Record<string, unknown>;
  decision: string | null;
  decided_at: number | null;
  note: string | null;
  incident: {
    segment_key: string;
    root_cause: string | null;
    confidence: number | null;
    at_risk_amount: number;
  } | null;
}

export interface LedgerPage {
  clock: string;
  total: number;
  kinds: string[];
  next_cursor: number | null;
  proves: string;
  entries: LedgerEntry[];
}

export interface VerifyResult {
  ok: boolean;
  entries: number;
  head_hash: string | null;
  broken_seq: number | null;
  detail: string;
  message: string;
  genesis_hash: string;
  proves: string;
}

export interface RunAggregate {
  scenario: string;
  policy: string;
  seeds: number;
  at_risk_orders: number;
  at_risk_amount: number;
  at_risk_recovered_amount: number;
  at_risk_recovery_rate: number;
  at_risk_messages: number;
  recovered_amount: number;
  recovered_std: number;
  recovery_rate: number;
  messages: number;
  opt_outs: number;
  contacts_per_1000: number;
  escalations: number;
  detected: number;
  time_to_detect: number | null;
  violations: number;
  link_orders: number;
  steer_orders: number;
  organic_orders: number;
}

export interface ResultsRun {
  run_id: string;
  scenarios: string[];
  seeds: number[];
  policies: string[];
  variant: string;
  at_risk_measured: boolean;
  aggregates: RunAggregate[];
  worlds: number;
  worlds_identical: boolean;
  violations: number;
  notes: string[];
  diagnosis: any;
  volume_sweep: any;
  sensitivity: any;
  fault_injection: any;
}

export interface SimStatus {
  running: boolean;
  scenario: string | null;
  seed: number | null;
  policy: string | null;
  started_at: number;
  finished_at: number;
  error: string | null;
  stop_requested: boolean;
  summary: Record<string, number | string>;
}

export interface ControlStatus {
  env: string;
  kill_switch: boolean;
  llm_provider: string;
}

export interface Health extends ControlStatus {
  status: string;
  version: string;
  token_configured: boolean;
}
