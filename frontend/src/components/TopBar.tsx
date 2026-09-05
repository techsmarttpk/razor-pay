import { useMerchant } from '../services/merchantContext'

export default function TopBar({ title, subtitle }: { title: string; subtitle?: string }) {
  const { merchants, merchantId, setMerchantId } = useMerchant()
  return (
    <div className="topbar">
      <div>
        <div className="page-title">{title}</div>
        {subtitle && <div className="page-sub">{subtitle}</div>}
      </div>
      <select
        className="merchant-select"
        value={merchantId ?? ''}
        onChange={e => setMerchantId(e.target.value || undefined)}
      >
        <option value="">All merchants</option>
        {merchants.map(m => (
          <option key={m.id} value={m.id}>{m.name} {m.exception_count ? `(${m.exception_count})` : ''}</option>
        ))}
      </select>
    </div>
  )
}
