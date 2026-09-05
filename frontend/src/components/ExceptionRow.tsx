import { useNavigate } from 'react-router-dom'
import { SeverityBadge, StatusBadge } from './Badges'
import { formatINR } from '../services/api'
import type { ExceptionSummary } from '../types'

export default function ExceptionRow({ exc }: { exc: ExceptionSummary }) {
  const navigate = useNavigate()
  return (
    <div className="exc-row" onClick={() => navigate(`/exceptions/${exc.id}`)}>
      <div className="exc-row-main">
        <div className="exc-row-title">{exc.exception_type.replace(/_/g, ' ')}</div>
        <div className="exc-row-merchant">{exc.merchant_name}</div>
      </div>
      <StatusBadge status={exc.status} />
      <SeverityBadge severity={exc.severity} />
      <div className="exc-row-amount">
        {formatINR(exc.money_at_risk)}
        <div className="sub">{Math.round(exc.confidence * 100)}% confidence</div>
      </div>
    </div>
  )
}
