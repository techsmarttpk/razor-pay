import { useEffect, useMemo, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer } from 'recharts'
import TopBar from '../components/TopBar'
import ExceptionRow from '../components/ExceptionRow'
import { api, formatINR } from '../services/api'
import { useMerchant } from '../services/merchantContext'
import type { ExceptionSummary } from '../types'

export default function MoneyAtRiskPage() {
  const { merchantId } = useMerchant()
  const [rows, setRows] = useState<ExceptionSummary[] | null>(null)

  useEffect(() => {
    setRows(null)
    api.exceptions({ merchant_id: merchantId, limit: 500 }).then(setRows)
  }, [merchantId])

  const chartData = useMemo(() => {
    if (!rows) return []
    const open = rows.filter(r => r.status !== 'resolved' && r.status !== 'auto_resolved')
    const byType = new Map<string, number>()
    for (const r of open) byType.set(r.exception_type, (byType.get(r.exception_type) ?? 0) + r.money_at_risk)
    return [...byType.entries()]
      .map(([type, amount]) => ({ type: type.replace(/_/g, ' '), amount }))
      .sort((a, b) => b.amount - a.amount)
  }, [rows])

  if (!rows) return <div className="loading">Loading…</div>

  const open = rows.filter(r => r.status !== 'resolved' && r.status !== 'auto_resolved').sort((a, b) => b.money_at_risk - a.money_at_risk)
  const total = open.reduce((s, r) => s + r.money_at_risk, 0)
  const recoverable = open.reduce((s, r) => s + r.recoverable_amount, 0)

  return (
    <>
      <TopBar title="Money at Risk" subtitle="Every open exception, ranked by rupees exposed — nothing here is estimated by an LLM" />

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(2, minmax(180px, 1fr))', maxWidth: 480 }}>
        <div className="card kpi-card">
          <div className="kpi-label">Total open exposure</div>
          <div className="kpi-value risk">{formatINR(total)}</div>
        </div>
        <div className="card kpi-card">
          <div className="kpi-label">Of which recoverable</div>
          <div className="kpi-value recoverable">{formatINR(recoverable)}</div>
        </div>
      </div>

      <div className="section-title">Exposure by exception type</div>
      <div className="card" style={{ height: 280, marginBottom: 8 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} layout="vertical" margin={{ left: 24, right: 24, top: 8, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1a2432" horizontal={false} />
            <XAxis type="number" tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`} stroke="#64748b" fontSize={11} />
            <YAxis type="category" dataKey="type" width={160} stroke="#64748b" fontSize={11.5} />
            <Tooltip
              formatter={v => formatINR(Number(Array.isArray(v) ? v[0] : v))}
              contentStyle={{ background: '#131b26', border: '1px solid #232f40', borderRadius: 8, fontSize: 12 }}
            />
            <Bar dataKey="amount" fill="#f0475a" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="section-title">All open exceptions ({open.length})</div>
      <div className="exc-list">
        {open.length === 0 && <div className="empty-state">Nothing at risk right now.</div>}
        {open.map(e => <ExceptionRow key={e.id} exc={e} />)}
      </div>
    </>
  )
}
