import { NavLink } from 'react-router-dom'

const links = [
  { to: '/', label: 'Overview', end: true },
  { to: '/money-at-risk', label: 'Money at Risk' },
  { to: '/exceptions', label: 'Exceptions' },
  { to: '/events', label: 'Financial Events' },
  { to: '/investigate', label: 'Agent Investigation' },
  { to: '/recovery', label: 'Recovery / Actions' },
  { to: '/audit', label: 'Audit Trail' },
  { to: '/performance', label: 'Model Performance' },
]

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-title">Financial Control Agent</div>
        <div className="brand-sub">Razorpay · Track 04</div>
      </div>
      {links.map(l => (
        <NavLink key={l.to} to={l.to} end={l.end} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
          <span className="dot" />
          {l.label}
        </NavLink>
      ))}
    </aside>
  )
}
