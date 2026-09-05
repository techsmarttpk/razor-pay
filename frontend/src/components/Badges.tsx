export function SeverityBadge({ severity }: { severity: string }) {
  return <span className={`badge badge-${severity}`}>{severity}</span>
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${status}`}>{status.replace(/_/g, ' ')}</span>
}

export function CategoryBadge({ category }: { category: string }) {
  const cls = category === 'SAFE_AUTO_ACTION' ? 'badge-safe' : category === 'ESCALATE' ? 'badge-esc' : 'badge-review'
  const label = category === 'SAFE_AUTO_ACTION' ? 'safe auto' : category === 'ESCALATE' ? 'escalate' : 'review required'
  return <span className={`badge ${cls}`}>{label}</span>
}
