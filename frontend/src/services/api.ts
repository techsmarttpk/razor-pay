import axios from 'axios'
import type {
  Overview, ExceptionSummary, ExceptionDetail, FinancialEvent, Merchant, Metrics, AuditEventRow, ActionRow,
} from '../types'

const client = axios.create({ baseURL: '/api' })

export const api = {
  overview: (merchantId?: string) =>
    client.get<Overview>('/overview', { params: merchantId ? { merchant_id: merchantId } : {} }).then(r => r.data),

  merchants: () => client.get<Merchant[]>('/merchants').then(r => r.data),

  exceptions: (params: Record<string, string | number | undefined> = {}) =>
    client.get<ExceptionSummary[]>('/exceptions', { params }).then(r => r.data),

  exceptionDetail: (id: string) => client.get<ExceptionDetail>(`/exceptions/${id}`).then(r => r.data),

  executeAction: (exceptionId: string, actionType: string) =>
    client.post<ActionRow>(`/exceptions/${exceptionId}/actions/${actionType}`).then(r => r.data),

  actions: (params: Record<string, string | number | undefined> = {}) =>
    client.get<ActionRow[]>('/actions', { params }).then(r => r.data),

  events: (params: Record<string, string | number | undefined> = {}) =>
    client.get<FinancialEvent[]>('/events', { params }).then(r => r.data),

  audit: (params: Record<string, string | number | undefined> = {}) =>
    client.get<AuditEventRow[]>('/audit', { params }).then(r => r.data),

  metrics: () => client.get<Metrics>('/metrics').then(r => r.data),

  rerunPipeline: () => client.post('/pipeline/rerun').then(r => r.data),

  ask: (question: string, merchantId?: string) =>
    client.post<{ answer: string }>('/agent/ask', { question, merchant_id: merchantId }).then(r => r.data),
}

export function formatINR(amount: number): string {
  return '₹' + amount.toLocaleString('en-IN', { maximumFractionDigits: 0 })
}

export function formatPercent(v: number): string {
  return `${Math.round(v * 100)}%`
}
