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
    </>
  )
}
