export default function KpiCard({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'risk' | 'recoverable' }) {
  return (
    <div className="card kpi-card">
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value${tone ? ' ' + tone : ''}`}>{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  )
}
