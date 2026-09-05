import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import TopBar from '../components/TopBar'
import { CategoryBadge, StatusBadge } from '../components/Badges'
import { api, formatINR } from '../services/api'
import type { ActionRow } from '../types'

export default function RecoveryActionsPage() {
  const [rows, setRows] = useState<ActionRow[] | null>(null)
  const [statusFilter, setStatusFilter] = useState('')

  const load = () => {
    setRows(null)
    api.actions({ status: statusFilter || undefined, limit: 400 }).then(setRows)
  }

  useEffect(load, [statusFilter])

  if (!rows) return <><TopBar title="Recovery / Actions" /><div className="loading">Loading…</div></>

  const executed = rows.filter(r => r.status === 'executed')
  const pending = rows.filter(r => r.status === 'pending')
  const recoveredAmount = executed
    .filter(r => r.action_type === 'create_recovery_case')
    .reduce((s, r) => s + (r.money_at_risk ?? 0), 0)

  return (
    <>
      <TopBar title="Recovery / Actions" subtitle="Every bounded action the agent has taken or proposed" />

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(3, minmax(160px,1fr))', maxWidth: 620 }}>
        <div className="card kpi-card"><div className="kpi-label">Executed</div><div className="kpi-value">{executed.length}</div></div>
        <div className="card kpi-card"><div className="kpi-label">Pending review</div><div className="kpi-value">{pending.length}</div></div>
        <div className="card kpi-card"><div className="kpi-label">Recovery cases value</div><div className="kpi-value recoverable">{formatINR(recoveredAmount)}</div></div>
      </div>

      <div className="filters">
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          <option value="pending">Pending</option>
          <option value="executed">Executed</option>
        </select>
      </div>

      <table className="table">
        <thead>
          <tr><th>Action</th><th>Exception</th><th>Category</th><th>Status</th><th>When</th><th style={{ textAlign: 'right' }}>Amount</th></tr>
        </thead>
        <tbody>
          {rows.map(a => (
            <tr key={a.id}>
              <td>{a.action_type.replace(/_/g, ' ')}</td>
              <td><Link to={`/exceptions/${a.exception_id}`} style={{ color: 'var(--info)' }}>{(a.exception_type ?? '').replace(/_/g, ' ')}</Link></td>
              <td><CategoryBadge category={a.category} /></td>
              <td><StatusBadge status={a.status === 'executed' ? 'auto_resolved' : 'review_required'} /></td>
              <td>{a.executed_at ? new Date(a.executed_at).toLocaleString() : new Date(a.created_at).toLocaleString()}</td>
              <td style={{ textAlign: 'right' }}>{formatINR(a.money_at_risk ?? 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
