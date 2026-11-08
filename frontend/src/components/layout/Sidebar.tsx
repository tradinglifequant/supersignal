import React from 'react'
import { NavLink } from 'react-router-dom'

const navItems = [
  { path: '/', label: 'Overview', icon: '📊' },
  { path: '/scanner', label: 'Live Scanner', icon: '🔍' },
  { path: '/positions', label: 'Positions', icon: '📈' },
  { path: '/history', label: 'Trade History', icon: '📜' },
  { path: '/ai', label: 'AI Analysis', icon: '🤖' },
  { path: '/config', label: 'Configuration', icon: '⚙️' },
  { path: '/system', label: 'System Logs', icon: '🧾' },
]

export const Sidebar: React.FC = () => {
  return (
    <div style={{ width: 220, background: '#1e293b', color: '#e2e8f0', minHeight: 'calc(100vh - 49px)', padding: '16px 8px', display: 'flex', flexDirection: 'column', gap: 4 }}>
      {navItems.map((item) => (
        <NavLink
          key={item.path}
          to={item.path}
          style={({ isActive }) => ({
            display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderRadius: 8,
            background: isActive ? '#334155' : 'transparent', color: isActive ? '#f8fafc' : '#cbd5e1',
            textDecoration: 'none', fontWeight: isActive ? 600 : 400, fontSize: 14,
          })}
        >
          <span>{item.icon}</span> {item.label}
        </NavLink>
      ))}
      <div style={{ marginTop: 'auto', padding: 12, background: '#0f172a', borderRadius: 8, fontSize: 12, color: '#94a3b8' }}>
        <div style={{ fontWeight: 700, color: '#e2e8f0', marginBottom: 6 }}>Risk Notice</div>
        Stop-loss is modeled, not guaranteed. See docs.
      </div>
    </div>
  )
}
