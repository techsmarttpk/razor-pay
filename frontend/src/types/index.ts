export interface Overview {
  money_at_risk: number
  recoverable_amount: number
  active_exceptions: number
  auto_resolved: number
  pending_review: number
  escalated: number
  settlement_health: number
  refund_health: number
  reconciliation_health: number
  total_settled: number
  total_paid: number
  top_exceptions: ExceptionSummary[]
}

export interface ExceptionSummary {
  id: string
  exception_type: string
  merchant_id: string
  merchant_name: string
  money_at_risk: number
  recoverable_amount: number
  confidence: number
  severity: string
  status: string
  explanation: string
}

export interface EvidenceItem {
  type: string
  id: string
  summary: string
  fields: Record<string, unknown>
}

export interface MoneyComponent {
  component: string
  amount: number
  source_type: string
  source_id: string
}

export interface RootCause {
  hypotheses: { hypothesis: string; amount: number; raw_amount?: number; records: string[] }[]
  supporting_records: string[]
  contradicted_hypotheses: string[]
  calculations: Record<string, number>
  confidence: number
  final_classification: string
  currently_at_risk: number
}

export interface ActionRow {
  id: string
  exception_id: string
  action_type: string
  category: string
  status: string
  payload: Record<string, unknown>
  result: Record<string, unknown>
  created_at: string
  executed_at: string | null
  exception_type?: string
  merchant_id?: string
  money_at_risk?: number
}

export interface AuditEventRow {
  id: string
  timestamp: string
  entity_type: string
  entity_id: string
  trigger: string
  evidence_consulted: EvidenceItem[]
  calculations: Record<string, number>
  model_or_rule: string
  decision: string
  confidence: number
  action: string
  execution_outcome: string
  human_review_required: boolean
}

export interface ExceptionDetail extends ExceptionSummary {
  entity_type: string
  entity_id: string
  detected_at: string
  window_start: string
  window_end: string
  money_at_risk_breakdown: MoneyComponent[]
  detector: string
  evidence: EvidenceItem[]
  root_cause: RootCause
  root_cause_label: string
  recommended_action: string
  action_category: string
  case_id: string | null
  actions: ActionRow[]
  audit_trail: AuditEventRow[]
}

export interface FinancialEvent {
  event_type: string
  id: string
  merchant_id: string
  amount: number
  timestamp: string
  status: string
  detail: string
}

export interface Merchant {
  id: string
  name: string
  category: string
  risk_tier: string
  mdr_rate: number
  onboarded_at: string
  exception_count: number
}

export interface Metrics {
  generated_at: string
  holdout_labels: number
  calibration_labels: number
  total_records: number
  detected_entities: number
  true_positives: number
  false_positives: number
  false_negatives: number
  true_negatives: number
  precision: number
  recall: number
  f1: number
  false_positive_rate: number
  root_cause_accuracy: number
  root_cause_evaluated_on: number
  money_at_risk_mape: number | null
  money_at_risk_samples: number
  auto_resolution_precision: number
  auto_resolution_evaluated_on: number
  processing_throughput_records_per_sec: number | null
  total_exceptions: number
  auto_resolved_count: number
  review_required_count: number
  escalated_count: number
  money_at_risk_open: number
  money_safely_resolved: number
  total_recoverable_amount: number
  by_scenario: Record<string, {
    holdout_count: number
    detected: number
    is_true_anomaly: boolean
    detection_rate: number | null
  }>
  ml_comparison: MlComparison | null
}

export interface MlDetectorResult {
  description: string
  precision: number
  recall: number
  f1: number
  false_positive_rate: number
  true_positives: number
  false_positives: number
  false_negatives: number
  true_negatives: number
  avg_inference_time_ms: number
  by_scenario: Record<string, {
    holdout_count: number
    detected: number
    detection_rate: number
  } | null>
}

export interface MlComparison {
  generated_at: string
  evaluation_population: {
    holdout_positive_merchants: number
    holdout_negative_merchants: number
  }
  model_metadata: {
    trained_at: string
    algorithm: string
    feature_columns: string[]
    random_state: number
    n_estimators: number
    contamination: number
    score_window_days: number
    train_cutoff_day: string
    train_rows: number
    train_merchants: number
    score_rows: number
    threshold: number
    calibration_metrics_at_threshold: { precision: number; recall: number; f1: number }
    fit_seconds: number
  }
  feature_rationale: Record<string, string>
  detectors: {
    existing_rules_combined: MlDetectorResult
    existing_statistical_heuristic: MlDetectorResult
    isolation_forest: MlDetectorResult
    ensemble_rules_or_ml: MlDetectorResult
  }
}
