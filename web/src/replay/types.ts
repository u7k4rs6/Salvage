/**
 * The shape of a recorded run.
 *
 * A recording is one complete `salvage agent run` captured off a throwaway database: the whole
 * hash chain plus read-only dumps of the three tables the chain does not cover. It is written by
 * the capture command in docs/BUILD_LOG.md and nothing in the web app ever writes one.
 *
 * `payload_json` is kept as the exact string the entry's hash commits to, so the chain verifies
 * from the file alone. Parsing it is the consumer's job, which is why `payload` is not a field.
 */

export interface RecordedLedgerEntry {
  seq: number;
  ts: number;
  kind: string;
  ref_type: string;
  ref_id: string;
  payload_json: string;
  prev_hash: string;
  hash: string;
}

/**
 * Columnar, because the row-per-object form of nineteen thousand windows was four times the size
 * for the same numbers. `fields` names the tuple positions so the file stays self-describing.
 */
export interface RecordedSegmentStats {
  keys: string[];
  fields: string[];
  rows: [number, number, number, number, number, number][];
}

export interface RecordedCase {
  id: string;
  order_id: string;
  incident_id: string | null;
  state: string;
  outcome: string | null;
  attempts: number;
  link_id: string | null;
  ttl_at: number;
  updated_at: number;
}

export interface RecordedRoute {
  order_id: string;
  route: string;
  paid_at: number;
  case_id: string | null;
}

export interface RecordedIncident {
  id: string;
  segment_key: string;
  opened_at: number;
  closed_at: number | null;
  at_risk_amount: number;
  rules_cause: string | null;
  llm_cause: string | null;
  root_cause: string | null;
  confidence: number | null;
  status: string;
  affected_scope_json: string;
}

export interface RecordedEscalation {
  id: string;
  incident_id: string;
  reason: string;
  decision: string | null;
  decided_at: number | null;
  created_at: number;
}

export interface RecordingMeta {
  artifact: string;
  version: number;
  run_id: string;
  scenario: string;
  seed: number;
  variant: string;
  policy: string;
  provider: string;
  fixture_misses: number;
  params_hash: string;
  sim_start: number;
  sim_end: number;
  eval_day_start: number;
  span: { start: number; end: number };
  genesis_hash: string;
  captured_at: number;
  git_rev: string;
  detector: {
    window_seconds: number;
    step_seconds: number;
    min_attempts: number;
    min_absolute_excess: number;
    consecutive_windows: number;
    close_within_of_baseline: number;
    close_consecutive_windows: number;
  };
  thresholds: {
    action_confidence: number;
    value_paise: number;
    max_nudges_per_incident: number;
    max_nudges_per_7_days: number;
    quiet_hours_start: number;
    quiet_hours_end: number;
    order_ttl_seconds: number;
  };
}

export interface Recording {
  _note: string;
  meta: RecordingMeta;
  ledger: RecordedLedgerEntry[];
  segments_stats: RecordedSegmentStats;
  recovery_cases: RecordedCase[];
  recovery_routes: RecordedRoute[];
  incidents: RecordedIncident[];
  escalations: RecordedEscalation[];
  sim_truth_incidents: {
    id: string;
    run_id: string;
    scenario: string;
    segment_selector: string;
    true_cause: string;
    start_ts: number;
    end_ts: number;
  }[];
}

// -- ledger payloads, as far as this page reads them -------------------------
//
// Every field below is one the recorded payload actually carries. Nothing is optional because the
// page would like a default; a field is optional here exactly when the writer can omit it.

export interface GateRecord {
  rule: string;
  passed: boolean;
  detail: string;
}

export interface SimRunStartedPayload {
  scenario: string;
  seed: number;
  variant: string;
  params_hash: string;
  warmup_days: number;
  eval_days: number;
  settle_days: number;
  attempts_per_day: number;
  faults: { start_ts: number; end_ts: number; selector: Record<string, string> }[];
}

export interface IncidentOpenedPayload {
  segment_key: string;
  affected_scope: string[];
  window_start: number;
  window_end: number;
  at_risk_amount: number;
}

export interface IncidentClosedPayload {
  segment_key: string;
  closed_at: number;
}

export interface EvidencePayload {
  segment_key: string;
  affected_scope: string[];
  window_start: number;
  window_end: number;
  attempts: number;
  failures: number;
  rate: number;
  baseline_rate: number;
  excess_failures: number;
  share_of_merchant_volume: number;
  error_source_dist: Record<string, number>;
  error_step_dist: Record<string, number>;
  error_reason_dist: Record<string, number>;
  error_code_top5: string[];
  sample_descriptions: string[];
  sibling_segments: Record<string, string>;
  trend: string;
  merchant_config_changed_recently: boolean;
  minutes_since_onset: number;
}

export interface ReconciledPayload {
  rules_cause: string;
  llm_cause: string | null;
  root_cause: string;
  confidence: number;
  agreed: boolean | null;
  escalate: boolean;
  escalation_reason: string | null;
  rules_detail: string;
  rationale: string;
  evidence: EvidencePayload;
}

export interface PlannedActionRecord {
  type: string;
  scope: string;
  params: Record<string, unknown>;
}

export interface PlanPayload {
  plan: { incident_id: string; actions: PlannedActionRecord[]; rationale: string };
  planner_error: string | null;
  eligibility: {
    affected_orders: number;
    unpaid_orders: number;
    consented: number;
    consented_with_alternate: number;
    opted_out: number;
    hard_declined: number;
    above_value_threshold: number;
  };
}

export interface ActionPayload {
  incident_id: string;
  case_id: string | null;
  type: string;
  params: Record<string, unknown>;
  gates: GateRecord[];
}

export interface LinkPaidPayload {
  incident_id: string;
  link_id: string | null;
  amount: number;
}

export interface SteerRecoveredPayload {
  incident_id: string;
  amount: number;
}

export interface OptOutPayload {
  incident_id: string;
  nudge_number: number;
}

export interface EscalationOpenedPayload {
  incident_id: string;
  reason: string;
  proposed_action: unknown;
}
