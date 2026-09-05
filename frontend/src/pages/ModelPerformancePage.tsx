import { useEffect, useState } from 'react'
import TopBar from '../components/TopBar'
import { api, formatINR, formatPercent } from '../services/api'
import type { Metrics } from '../types'

function rateClass(rate: number | null, isTrueAnomaly: boolean) {
  if (rate === null) return ''
  const good = isTrueAnomaly ? rate >= 0.75 : rate <= 0.1
  const bad = isTrueAnomaly ? rate < 0.4 : rate > 0.3
  if (good) return 'rate-good'
  if (bad) return 'rate-bad'
  return 'rate-mid'
}

export default function ModelPerformancePage() {
  const [m, setM] = useState<Metrics | null>(null)

  useEffect(() => { api.metrics().then(setM) }, [])

  if (!m) return <><TopBar title="Model Performance" /><div className="loading">Loading…</div></>

  return (
    <>
      <TopBar title="Model Performance" subtitle={`Evaluated on a held-out label split never used to pick thresholds · generated ${new Date(m.generated_at).toLocaleString()}`} />

      <div className="card" style={{ marginBottom: 20, borderColor: '#2a3a2f' }}>
        These numbers are computed directly from {m.holdout_labels} held-out ground-truth labels
        ({m.calibration_labels} separate labels were used only to sanity-check detector thresholds).
        Nothing on this page is hardcoded.
      </div>

      <div className="kpi-grid">
        <div className="metric-tile"><div className="v">{formatPercent(m.precision)}</div><div className="l">Precision</div></div>
        <div className="metric-tile"><div className="v">{formatPercent(m.recall)}</div><div className="l">Recall</div></div>
        <div className="metric-tile"><div className="v">{formatPercent(m.f1)}</div><div className="l">F1</div></div>
        <div className="metric-tile"><div className="v">{formatPercent(m.false_positive_rate)}</div><div className="l">False Positive Rate</div></div>
        <div className="metric-tile"><div className="v">{formatPercent(m.root_cause_accuracy)}</div><div className="l">Root Cause Accuracy</div></div>
        <div className="metric-tile"><div className="v">{m.money_at_risk_mape !== null ? formatPercent(m.money_at_risk_mape) : '—'}</div><div className="l">Money-at-Risk Est. Error</div></div>
        <div className="metric-tile"><div className="v">{formatPercent(m.auto_resolution_precision)}</div><div className="l">Auto-resolution Precision</div></div>
        <div className="metric-tile"><div className="v">{m.processing_throughput_records_per_sec?.toFixed(0) ?? '—'}/s</div><div className="l">Processing Throughput</div></div>
      </div>

      <div className="section-title">Confusion matrix (holdout)</div>
      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4, minmax(120px,1fr))', maxWidth: 620 }}>
        <div className="metric-tile"><div className="v">{m.true_positives}</div><div className="l">True Positives</div></div>
        <div className="metric-tile"><div className="v">{m.false_positives}</div><div className="l">False Positives</div></div>
        <div className="metric-tile"><div className="v">{m.false_negatives}</div><div className="l">Missed (FN)</div></div>
        <div className="metric-tile"><div className="v">{m.true_negatives}</div><div className="l">True Negatives</div></div>
      </div>

      <div className="section-title">Operational summary</div>
      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4, minmax(140px,1fr))' }}>
        <div className="metric-tile"><div className="v">{m.total_records.toLocaleString()}</div><div className="l">Total Records</div></div>
        <div className="metric-tile"><div className="v">{m.total_exceptions}</div><div className="l">Exceptions Raised</div></div>
        <div className="metric-tile"><div className="v">{m.auto_resolved_count}</div><div className="l">Auto-resolved</div></div>
        <div className="metric-tile"><div className="v">{m.escalated_count}</div><div className="l">Escalated</div></div>
        <div className="metric-tile"><div className="v">{formatINR(m.money_at_risk_open)}</div><div className="l">Money at Risk (open)</div></div>
        <div className="metric-tile"><div className="v">{formatINR(m.money_safely_resolved)}</div><div className="l">Money Safely Resolved</div></div>
        <div className="metric-tile"><div className="v">{formatINR(m.total_recoverable_amount)}</div><div className="l">Total Recoverable</div></div>
        <div className="metric-tile"><div className="v">{m.review_required_count}</div><div className="l">Pending Review</div></div>
      </div>

      <div className="section-title">Detection rate by injected scenario (holdout only)</div>
      <table className="table scenario-table">
        <thead>
          <tr><th>Scenario</th><th>Ground truth type</th><th>Holdout count</th><th>Detected</th><th>Detection rate</th></tr>
        </thead>
        <tbody>
          {Object.entries(m.by_scenario).sort((a, b) => a[0].localeCompare(b[0])).map(([scenario, s]) => (
            <tr key={scenario}>
              <td>{scenario.replace(/_/g, ' ')}</td>
              <td>{s.is_true_anomaly ? 'true anomaly' : 'benign / negative'}</td>
              <td>{s.holdout_count}</td>
              <td>{s.detected}</td>
              <td className={rateClass(s.detection_rate, s.is_true_anomaly)}>
                {s.detection_rate !== null ? formatPercent(s.detection_rate) : '—'}
                {!s.is_true_anomaly && s.detection_rate !== null && ' (lower is better)'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {m.ml_comparison && <MlModelSection ml={m.ml_comparison} />}
    </>
  )
}

function MlModelSection({ ml }: { ml: NonNullable<Metrics['ml_comparison']> }) {
  const meta = ml.model_metadata
  const rows: [string, keyof typeof ml.detectors][] = [
    ['Existing rules (combined specialized detectors)', 'existing_rules_combined'],
    ['Existing statistical heuristic (replaced detector)', 'existing_statistical_heuristic'],
    ['Isolation Forest (trained ML model)', 'isolation_forest'],
    ['Ensemble (rules OR Isolation Forest)', 'ensemble_rules_or_ml'],
  ]
  const n = ml.evaluation_population.holdout_positive_merchants + ml.evaluation_population.holdout_negative_merchants

  return (
    <>
      <div className="section-title">ML model: merchant-level anomaly detection</div>
      <div className="card" style={{ marginBottom: 20, borderColor: '#2a3a2f' }}>
        A real <code>sklearn.ensemble.IsolationForest</code> trained on {meta.train_rows} merchant-day rows
        ({meta.train_merchants} merchants) up to {meta.train_cutoff_day}, then scored on the {meta.score_rows}
        merchant-day rows after that cutoff — the model never saw the rows it is evaluated on. Compared below
        against the existing rule/statistical detectors on the exact same {n}-merchant holdout population
        (only {ml.evaluation_population.holdout_positive_merchants} carry a true merchant-level anomaly label —
        small enough that these numbers are directional, not statistically conclusive; see claude.md).
      </div>

      <table className="table scenario-table">
        <thead>
          <tr>
            <th>Detector</th><th>Precision</th><th>Recall</th><th>F1</th>
            <th>False Positive Rate</th><th>Avg inference time</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, key]) => {
            const r = ml.detectors[key]
            return (
              <tr key={key}>
                <td>{label}<div style={{ fontSize: 12, opacity: 0.65 }}>{r.description}</div></td>
                <td>{formatPercent(r.precision)}</td>
                <td>{formatPercent(r.recall)}</td>
                <td>{formatPercent(r.f1)}</td>
                <td>{formatPercent(r.false_positive_rate)}</td>
                <td>{r.avg_inference_time_ms < 1 ? `${(r.avg_inference_time_ms * 1000).toFixed(0)}µs` : `${r.avg_inference_time_ms.toFixed(2)}ms`}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <div className="section-title">Model configuration (from data/models/isolation_forest_meta.json)</div>
      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4, minmax(160px,1fr))' }}>
        <div className="metric-tile"><div className="v">{meta.n_estimators}</div><div className="l">Trees</div></div>
        <div className="metric-tile"><div className="v">{meta.contamination}</div><div className="l">Contamination Assumption</div></div>
        <div className="metric-tile"><div className="v">{meta.random_state}</div><div className="l">Random Seed</div></div>
        <div className="metric-tile"><div className="v">{meta.threshold.toFixed(4)}</div><div className="l">Selected Threshold</div></div>
        <div className="metric-tile"><div className="v">{formatPercent(meta.calibration_metrics_at_threshold.f1)}</div><div className="l">Calibration F1 at Threshold</div></div>
        <div className="metric-tile"><div className="v">{meta.fit_seconds.toFixed(2)}s</div><div className="l">Fit Time</div></div>
        <div className="metric-tile"><div className="v">{meta.score_window_days}d</div><div className="l">Scored Window</div></div>
        <div className="metric-tile"><div className="v">{new Date(meta.trained_at).toLocaleString()}</div><div className="l">Trained At</div></div>
      </div>

      <div className="section-title">Engineered features (13)</div>
      <table className="table scenario-table">
        <thead><tr><th>Feature</th><th>Why it can indicate an anomaly</th></tr></thead>
        <tbody>
          {meta.feature_columns.map(f => (
            <tr key={f}>
              <td><code>{f}</code></td>
              <td style={{ fontSize: 13 }}>{ml.feature_rationale[f]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
