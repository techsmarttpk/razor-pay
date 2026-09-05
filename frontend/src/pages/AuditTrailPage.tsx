import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import TopBar from '../components/TopBar'
import { api } from '../services/api'
import type { AuditEventRow } from '../types'

export default function AuditTrailPage() {
  const [rows, setRows] = useState<AuditEventRow[] | null>(null)

  useEffect(() => { api.audit({ limit: 400 }).then(setRows) }, [])

  if (!rows) return <><TopBar title="Audit Trail" /><div className="loading">Loading…</div></>

  return (
    <>
      <TopBar title="Audit Trail" subtitle="Append-only log of every agent decision — evidence, calculation, rule, decision, action, outcome" />
      <table className="table">
        <thead>
          <tr>
            <th>Time</th><th>Entity</th><th>Rule / Model</th><th>Decision</th><th>Confidence</th><th>Outcome</th><th>Review?</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(a => (
            <tr key={a.id}>
              <td style={{ whiteSpace: 'nowrap' }}>{new Date(a.timestamp).toLocaleString()}</td>
              <td>
                {a.entity_type === 'exception'
                  ? <Link to={`/exceptions/${a.entity_id}`} style={{ color: 'var(--info)' }}>{a.entity_id}</Link>
                  : a.entity_id}
              </td>
              <td>{a.model_or_rule}</td>
              <td>{a.decision}</td>
              <td>{Math.round(a.confidence * 100)}%</td>
              <td>{a.execution_outcome}</td>
              <td>{a.human_review_required ? 'yes' : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
