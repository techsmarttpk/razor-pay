import { useState } from 'react'
import TopBar from '../components/TopBar'
import { api } from '../services/api'
import { useMerchant } from '../services/merchantContext'

interface Msg { role: 'user' | 'agent'; text: string }

const SUGGESTIONS = [
  'Why is money at risk today?',
  'What is the biggest exception right now?',
  'How much has been auto-resolved?',
]

export default function AgentInvestigationPage() {
  const { merchantId } = useMerchant()
  const [messages, setMessages] = useState<Msg[]>([
    { role: 'agent', text: 'Ask me about current exceptions, money at risk, or root causes. Every number I give you comes straight from the deterministic engines — I never invent a figure.' },
  ])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)

  const send = async (question: string) => {
    if (!question.trim()) return
    setMessages(m => [...m, { role: 'user', text: question }])
    setInput('')
    setBusy(true)
    try {
      const res = await api.ask(question, merchantId)
      setMessages(m => [...m, { role: 'agent', text: res.answer }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <TopBar title="Agent Investigation" subtitle="Secondary interaction — the product works fully without this" />
      <div className="pill-row" style={{ marginBottom: 16 }}>
        {SUGGESTIONS.map(s => (
          <button key={s} className="btn" onClick={() => send(s)} disabled={busy}>{s}</button>
        ))}
      </div>
      <div className="chat-panel">
        <div className="chat-messages">
          {messages.map((m, i) => (
            <div key={i} className={`chat-bubble ${m.role}`}>{m.text}</div>
          ))}
          {busy && <div className="chat-bubble agent">…</div>}
        </div>
        <div className="chat-input-row">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') send(input) }}
            placeholder="Ask about money at risk, root causes, or exceptions…"
          />
          <button className="btn btn-primary" onClick={() => send(input)} disabled={busy}>Send</button>
        </div>
      </div>
    </>
  )
}
