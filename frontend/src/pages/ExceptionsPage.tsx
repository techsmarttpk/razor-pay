import { useEffect, useState } from 'react'
import TopBar from '../components/TopBar'
import ExceptionRow from '../components/ExceptionRow'
import { api } from '../services/api'
import { useMerchant } from '../services/merchantContext'
import type { ExceptionSummary } from '../types'

const STATUSES = ['open', 'auto_resolved', 'review_required', 'escalated', 'resolved']
const SEVERITIES = ['critical', 'high', 'medium', 'low']

export default function ExceptionsPage() {
  const { merchantId } = useMerchant()
  const [rows, setRows] = useState<ExceptionSummary[] | null>(null)
  const [status, setStatus] = useState('')
  const [severity, setSeverity] = useState('')
  const [type, setType] = useState('')

  useEffect(() => {
    setRows(null)
    api.exceptions({
      merchant_id: merchantId, limit: 500,
      status: status || undefined, severity: severity || undefined, exception_type: type || undefined,
    }).then(setRows)
  }, [merchantId, status, severity, type])

  const types = Array.from(new Set((rows ?? []).map(r => r.exception_type))).sort()

  return (
    <>
      <TopBar title="Exceptions" subtitle="Every detected financial control exception across the merchant portfolio" />

      <div className="filters">
        <select value={status} onChange={e => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
        </select>
        <select value={severity} onChange={e => setSeverity(e.target.value)}>
          <option value="">All severities</option>
          {SEVERITIES.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={type} onChange={e => setType(e.target.value)}>
          <option value="">All types</option>
          {types.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
        </select>
      </div>

      {!rows ? <div className="loading">Loading…</div> : (
        <div className="exc-list">
          {rows.length === 0 && <div className="empty-state">No exceptions match these filters.</div>}
          {rows.map(e => <ExceptionRow key={e.id} exc={e} />)}
        </div>
      )}
    </>
  )
}
