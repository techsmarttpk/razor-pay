import { useEffect, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import TopBar from '../components/TopBar'
import { SeverityBadge, StatusBadge, CategoryBadge } from '../components/Badges'
import { api, formatINR } from '../services/api'
import type { ExceptionDetail } from '../types'

export default function ExceptionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [exc, setExc] = useState<ExceptionDetail | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(() => {
    if (id) api.exceptionDetail(id).then(setExc)
  }, [id])

  useEffect(() => { load() }, [load])

  if (!exc) return <div className="loading">Loading exception…</div>

  const runAction = async (actionType: string) => {
    setBusy(actionType)
    try {
      await api.executeAction(exc.id, actionType)
      load()
    } finally {
      setBusy(null)
    }
  }

  const rc = exc.root_cause

  return (
    <>
      <div className="breadcrumb">
        <Link to="/exceptions">Exceptions</Link> <span>/</span> <span>{exc.id}</span>
      </div>
      <TopBar title={exc.exception_type.replace(/_/g, ' ')} subtitle={`${exc.merchant_name} · detected ${new Date(exc.detected_at).toLocaleString()}`} />

      <div className="pill-row" style={{ marginBottom: 18 }}>
        <StatusBadge status={exc.status} />
        <SeverityBadge severity={exc.severity} />
        <CategoryBadge category={exc.action_category} />
        <span className="badge" style={{ background: 'var(--info-bg)', color: 'var(--info)' }}>{Math.round(exc.confidence * 100)}% confidence</span>
      </div>

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(2, minmax(180px,1fr))', maxWidth: 480 }}>
        <div className="card kpi-card">
          <div className="kpi-label">Money at Risk</div>
          <div className="kpi-value risk">{formatINR(exc.money_at_risk)}</div>
        </div>
        <div className="card kpi-card">
          <div className="kpi-label">Recoverable</div>
          <div className="kpi-value recoverable">{formatINR(exc.recoverable_amount)}</div>
        </div>
      </div>

      <div className="two-col">
        <div>
          <div className="section-title">WHY — Agent explanation</div>
          <div className="card">{exc.explanation}</div>

          <div className="section-title">EVIDENCE</div>
          {exc.evidence.map((ev, i) => (
            <div className="evidence-card" key={i}>
              <div className="evidence-summary">{ev.summary}</div>
              <div className="evidence-fields">
                {Object.entries(ev.fields).map(([k, v]) => (
                  <span key={k}><b>{k.replace(/_/g, ' ')}:</b> {String(v)}</span>
                ))}
              </div>
            </div>
          ))}

          <div className="section-title">CALCULATION — Money at risk breakdown</div>
          <div className="card">
            {exc.money_at_risk_breakdown.map((c, i) => (
              <div className="breakdown-row" key={i}>
                <span>{c.component.replace(/_/g, ' ')} <span style={{ color: 'var(--text-faint)' }}>({c.source_type} {c.source_id})</span></span>
                <span className="amt">{formatINR(c.amount)}</span>
              </div>
            ))}
            <div className="breakdown-row" style={{ fontWeight: 700 }}>
              <span>Total money at risk</span>
              <span className="amt">{formatINR(exc.money_at_risk)}</span>
            </div>
          </div>

          <div className="section-title">ROOT CAUSE — Diagnostic tree</div>
          <div className="card">
            {rc.hypotheses.map((h, i) => (
              <div className="tree-node confirmed" key={i}>
                <div className="tree-node-label">{h.hypothesis.replace(/_/g, ' ')}
                  {h.hypothesis === rc.final_classification && <span style={{ color: 'var(--recoverable)', marginLeft: 8, fontSize: 11 }}>● FINAL CLASSIFICATION</span>}
                </div>
                <div className="tree-node-amt">
                  {formatINR(h.amount)}{h.raw_amount && h.raw_amount !== h.amount ? ` (raw signal: ${formatINR(h.raw_amount)}, capped to remaining variance)` : ''}
                  {' · '}{h.records.length} record(s)
                </div>
              </div>
            ))}
            {rc.contradicted_hypotheses.map((h, i) => (
              <div className="tree-node contradicted" key={i}>
                <div className="tree-node-label">{h.replace(/_/g, ' ')}</div>
                <div className="tree-node-amt">no supporting evidence found — ruled out</div>
              </div>
            ))}
            {rc.final_classification === 'unresolved_exception' && (
              <div style={{ marginTop: 10, fontSize: 12.5, color: 'var(--warning)' }}>
                No single hypothesis explains the full amount — classified as unresolved and escalated.
              </div>
            )}
          </div>

          <div className="section-title">AGENT DECISION → ACTION</div>
          <div className="card">
            <div style={{ marginBottom: 10 }}>
              Recommended action: <b>{exc.recommended_action.replace(/_/g, ' ')}</b> — category <CategoryBadge category={exc.action_category} />
            </div>
            <div className="btn-row">
              <button className="btn btn-safe" disabled={busy !== null} onClick={() => runAction('mark_resolved')}>
                {busy === 'mark_resolved' ? 'Resolving…' : 'RESOLVE SAFE ITEMS'}
              </button>
              <button className="btn btn-danger" disabled={busy !== null} onClick={() => runAction('generate_merchant_alert')}>
                {busy === 'generate_merchant_alert' ? 'Escalating…' : `ESCALATE ${formatINR(exc.money_at_risk)}`}
              </button>
              <button className="btn" disabled={busy !== null} onClick={() => runAction('create_recovery_case')}>
                Create recovery case
              </button>
              <button className="btn" disabled={busy !== null} onClick={() => runAction('group_related_exceptions')}>
                Group related exceptions
              </button>
            </div>
          </div>

          <div className="section-title">RESULT — Actions taken</div>
          {exc.actions.length === 0 && <div className="card empty-state">No actions executed yet.</div>}
          {exc.actions.map(a => (
            <div className="card" key={a.id} style={{ marginBottom: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <b>{a.action_type.replace(/_/g, ' ')}</b>
                <StatusBadge status={a.status === 'executed' ? 'auto_resolved' : 'review_required'} />
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-faint)' }}>
                {a.executed_at ? `Executed ${new Date(a.executed_at).toLocaleString()}` : 'Pending operator review'}
              </div>
            </div>
          ))}
        </div>

        <div>
          <div className="section-title">AUDIT TRAIL</div>
          <div className="card">
            {exc.audit_trail.length === 0 && <div className="empty-state">No audit events.</div>}
            {exc.audit_trail.map(a => (
              <div className="audit-step" key={a.id}>
                <div className="audit-time">{new Date(a.timestamp).toLocaleTimeString()}</div>
                <div>
                  <div className="audit-decision">{a.decision}</div>
                  <div className="audit-meta">
                    rule: {a.model_or_rule} · confidence {Math.round(a.confidence * 100)}%
                    {a.human_review_required && ' · human review required'}
                  </div>
                  <div className="audit-meta">outcome: {a.execution_outcome}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
