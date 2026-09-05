import { useEffect, useState } from 'react'
import TopBar from '../components/TopBar'
import KpiCard from '../components/KpiCard'
import HealthGauge from '../components/HealthGauge'
import ExceptionRow from '../components/ExceptionRow'
import { api, formatINR } from '../services/api'
import { useMerchant } from '../services/merchantContext'
import type { Overview } from '../types'

export default function OverviewPage() {
  const { merchantId } = useMerchant()
  const [data, setData] = useState<Overview | null>(null)

  useEffect(() => {
    setData(null)
    api.overview(merchantId).then(setData)
  }, [merchantId])

  if (!data) return <div className="loading">Loading financial control room…</div>

  const hero = data.top_exceptions[0]

  return (
    <>
      <TopBar title="Financial Control Room" subtitle="Continuous monitoring of Razorpay merchant settlement, refund and fee integrity" />

      <div className="kpi-grid">
        <KpiCard label="Money at Risk" value={formatINR(data.money_at_risk)} tone="risk" sub={`${data.active_exceptions} active exceptions`} />
        <KpiCard label="Recoverable Money" value={formatINR(data.recoverable_amount)} tone="recoverable" sub="deterministically calculated" />
        <KpiCard label="Auto-resolved" value={String(data.auto_resolved)} sub="safe bounded actions executed" />
        <KpiCard label="Pending Review" value={String(data.pending_review)} sub="awaiting operator decision" />
        <KpiCard label="Escalated" value={String(data.escalated)} sub="low confidence or high value" />
      </div>

      {hero && (
        <div className="card" style={{ marginBottom: 24, borderColor: '#3a2230' }}>
          <div style={{ fontSize: 12, color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600, marginBottom: 8 }}>
            Top signal
          </div>
          <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--risk)', marginBottom: 6 }}>
            {formatINR(hero.money_at_risk)} at risk — {hero.exception_type.replace(/_/g, ' ')}
          </div>
          <div style={{ color: 'var(--text-dim)', marginBottom: 12, maxWidth: 720 }}>{hero.explanation}</div>
          <a className="btn btn-primary" href={`/exceptions/${hero.id}`}>Investigate →</a>
        </div>
      )}

      <div className="section-title">Health</div>
      <div className="gauge-grid" style={{ marginBottom: 8 }}>
        <HealthGauge label="Settlement Health" value={data.settlement_health} />
        <HealthGauge label="Refund Health" value={data.refund_health} />
        <HealthGauge label="Reconciliation Health" value={data.reconciliation_health} />
      </div>

      <div className="section-title">Top exceptions by money at risk</div>
      <div className="exc-list">
        {data.top_exceptions.length === 0 && <div className="empty-state">No open exceptions — everything reconciled.</div>}
        {data.top_exceptions.map(e => <ExceptionRow key={e.id} exc={e} />)}
      </div>
    </>
  )
}
