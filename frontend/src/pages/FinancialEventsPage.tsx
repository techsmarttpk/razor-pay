import { useEffect, useState } from 'react'
import TopBar from '../components/TopBar'
import { api, formatINR } from '../services/api'
import { useMerchant } from '../services/merchantContext'
import type { FinancialEvent } from '../types'

const TYPES = ['payment', 'refund', 'settlement', 'dispute']

export default function FinancialEventsPage() {
  const { merchantId } = useMerchant()
  const [rows, setRows] = useState<FinancialEvent[] | null>(null)
  const [type, setType] = useState('')

  useEffect(() => {
    setRows(null)
    api.events({ merchant_id: merchantId, entity_type: type || undefined, limit: 300 }).then(setRows)
  }, [merchantId, type])

  return (
    <>
      <TopBar title="Financial Events" subtitle="Unified feed of payments, refunds, settlements and disputes" />
      <div className="filters">
        <select value={type} onChange={e => setType(e.target.value)}>
          <option value="">All event types</option>
          {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      {!rows ? <div className="loading">Loading…</div> : (
        <table className="table">
          <thead>
            <tr><th>Time</th><th>Type</th><th>Detail</th><th>Status</th><th style={{ textAlign: 'right' }}>Amount</th></tr>
          </thead>
          <tbody>
            {rows.map(e => (
              <tr key={e.event_type + e.id}>
                <td>{e.timestamp ? new Date(e.timestamp).toLocaleString() : '—'}</td>
                <td style={{ textTransform: 'capitalize' }}>{e.event_type}</td>
                <td>{e.detail}</td>
                <td>{e.status}</td>
                <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: e.amount < 0 ? 'var(--risk)' : 'var(--text)' }}>
                  {formatINR(e.amount)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}
